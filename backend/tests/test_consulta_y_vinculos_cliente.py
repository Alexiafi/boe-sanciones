"""Session 5 fixes reported from the delivery walkthrough:

- "Consulta por DNI/CIF" must find a CIF that the 30-day panel shows
  (structured ``sancionados``), not only regex-index documents;
- documents downloaded before the historical index existed get indexed
  for free (``tasks/historico_reindexado.py``);
- a client's history search also attaches already-extracted opportunities
  by identifier (client's own and its vínculos');
- a vínculo (administrador…) can be promoted to its own client ficha, with
  the link kept in both directions and its sanctions moved along;
- "Solo mis clientes" in /notificaciones includes sanctions converted by
  hand, not only the ones the pipeline matched later;
- runtime configuration round-trips through the API.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SyncSessionLocal
from app.main import app
from app.models.cliente import ActividadCliente, Cliente, VinculoCliente
from app.models.documento import BoeDocumento
from app.models.historico import HistoricoDoc
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.services.historico.busqueda import buscar_historico, consultar_historico
from app.services.notifier import create_inapp_notification
from app.services.oportunidades import allocate_codigo
from app.services.vinculos import indice_identificadores
from app.tasks.historico_reindexado import pendientes_de_reindexar, reindexar_documentos_descargados

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _sancion(session, *, boe_id: str, nombre: str | None, identificador: str | None, texto: str | None = None,
             fecha=date(2026, 8, 3), matricula: str | None = None, source: str | None = None, notificar: bool = False) -> Sancionado:
    doc = BoeDocumento(boe_id=boe_id, fecha_publicacion=fecha, titulo=f"Doc {boe_id}", texto_plano=texto, source=source)
    session.add(doc)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=doc.id, codigo=allocate_codigo(session, fecha.year), estado_oportunidad="nueva",
        origen_clave=f"clave-{boe_id}", nombre=nombre, identificador=identificador, matricula_coche=matricula,
        tipo_persona="juridica" if identificador and identificador[0].isalpha() else "fisica",
        tipo_identificador="CIF" if identificador and identificador[0].isalpha() else "DNI",
        importe_multa_eur=120,
    )
    session.add(sancionado)
    session.flush()
    if notificar:
        create_inapp_notification(session, sancionado)
    return sancionado


def _cliente(session, sancionado: Sancionado, *, codigo="CLI-2026-9001", cif=None, dni=None) -> Cliente:
    cliente = Cliente(
        codigo=codigo, nombre_razon_social=sancionado.nombre or "Cliente", cif_nif=cif, dni_nie=dni,
        sancion_origen_id=sancionado.id, tipo_persona=sancionado.tipo_persona,
    )
    session.add(cliente)
    session.flush()
    sancionado.cliente_id = cliente.id
    sancionado.estado_oportunidad = "cliente"
    return cliente


# --- consulta -----------------------------------------------------------------

@pytest.mark.integration
def test_consulta_finds_cif_from_the_30_day_panel_even_if_not_indexed(clean_database):
    """The exact bug from the walkthrough: a CIF copied from a sanction on the
    panel returned nothing because that document predates the index."""
    session = SyncSessionLocal()
    try:
        _sancion(session, boe_id="BOE-N-2026-588934", nombre="B95958617", identificador="B95958617", texto="…")
        _sancion(session, boe_id="BOE-A-2026-1", nombre="Otra SL", identificador="B-11.111.111", matricula="1234 BCD")
        session.commit()

        por_cif = consultar_historico(session, cif="b95958617")
        assert len(por_cif["resultados"]) == 1
        hit = por_cif["resultados"][0]
        assert hit["tipo"] == "sancion" and hit["via_match"] == "cif" and hit["score"] == 1.0
        assert hit["sancionado_id"] is not None and hit["codigo"].startswith("OP-")
        assert hit["boe_id"] == "BOE-N-2026-588934" and hit["fuente"] == "teu"
        assert hit["url_documento"].startswith("https://www.boe.es/boe_n/dias/2026/08/03/not.php?id=BOE-N-2026-588934")

        # Stored with separators, typed without them (and vice versa).
        assert consultar_historico(session, cif="B11111111")["resultados"][0]["nombre"] == "Otra SL"
        assert consultar_historico(session, matricula="1234bcd")["resultados"][0]["via_match"] == "matricula"
        assert consultar_historico(session, nombre="otra sl")["resultados"][0]["via_match"] == "nombre"
        assert consultar_historico(session, cif="Z99999999")["resultados"] == []
    finally:
        session.close()


@pytest.mark.integration
def test_consulta_merges_index_and_panel_without_duplicating_a_document(clean_database):
    from app.services.historico.indexado import upsert_historico_doc

    session = SyncSessionLocal()
    try:
        _sancion(session, boe_id="BOE-A-2026-MIX", nombre="Mixta SL", identificador="B12345674")
        upsert_historico_doc(
            session, boe_id="BOE-A-2026-MIX", fuente="boe", fecha_publicacion=date(2026, 8, 3), titulo="Mixta",
            origen_indexado="diario", texto="Sancionada MIXTA SL con CIF B12345674",
        )
        upsert_historico_doc(
            session, boe_id="BOE-A-2025-OLD", fuente="boe", fecha_publicacion=date(2025, 2, 1), titulo="Antiguo",
            origen_indexado="backfill", texto="Requerimiento a MIXTA SL, CIF B12345674",
        )
        session.commit()
        resultados = consultar_historico(session, cif="B12345674")["resultados"]
        assert [(r["boe_id"], r["tipo"]) for r in resultados] == [("BOE-A-2026-MIX", "sancion"), ("BOE-A-2025-OLD", "documento")]
    finally:
        session.close()


# --- reindex -------------------------------------------------------------------

@pytest.mark.integration
def test_reindex_indexes_downloaded_documents_for_free_and_is_idempotent(clean_database):
    session = SyncSessionLocal()
    try:
        _sancion(session, boe_id="BOE-N-2026-OLD1", nombre="X", identificador="B12345674", texto="Sancionado con CIF B12345674.")
        _sancion(session, boe_id="BOE-A-2026-OLD2", nombre="Y", identificador="44444444A", texto="Don Y con DNI 44444444A.")
        _sancion(session, boe_id="BOE-A-2026-NOTXT", nombre="Z", identificador=None, texto=None)
        _sancion(session, boe_id="MANUAL-ABC", nombre="Manual", identificador="B55555555", texto="alta manual", source="manual")
        session.commit()

        assert pendientes_de_reindexar(session) == 2
        stats = reindexar_documentos_descargados(session)
        assert stats == {"vistos": 3, "indexados": 2, "sin_texto": 1}
        docs = {d.boe_id: d for d in session.execute(select(HistoricoDoc)).scalars().all()}
        assert set(docs) == {"BOE-N-2026-OLD1", "BOE-A-2026-OLD2"}
        assert docs["BOE-N-2026-OLD1"].fuente == "teu" and docs["BOE-N-2026-OLD1"].identificadores == ["B12345674"]
        assert docs["BOE-A-2026-OLD2"].fuente == "boe" and docs["BOE-A-2026-OLD2"].texto_plano

        assert reindexar_documentos_descargados(session)["indexados"] == 0
        assert pendientes_de_reindexar(session) == 0
    finally:
        session.close()

    with TestClient(app) as client:
        assert client.get("/api/historico/reindexar/pendientes").json() == {"pendientes": 0}


# --- client search links panel opportunities --------------------------------------

@pytest.mark.integration
def test_client_history_search_attaches_existing_opportunities_by_identifier(clean_database):
    session = SyncSessionLocal()
    try:
        origen = _sancion(session, boe_id="BOE-A-2026-C0", nombre="Tarianet SL", identificador="B13981428")
        cliente = _cliente(session, origen, cif="B13981428")
        session.add(VinculoCliente(cliente_id=cliente.id, rol="Administrador", nombre="Pedro", tipo_persona="fisica", identificador="34262482X"))
        suelta_empresa = _sancion(session, boe_id="BOE-A-2026-C1", nombre="TARIANET, S.L.", identificador="B-13981428")
        suelta_admin = _sancion(session, boe_id="BOE-N-2026-C2", nombre="Pedro", identificador="34262482-X")
        ajena = _sancion(session, boe_id="BOE-A-2026-C3", nombre="Otra", identificador="B99999999")
        session.commit()

        resultado = buscar_historico(session, cliente)
        assert resultado["sanciones_vinculadas"] == 2
        session.refresh(suelta_empresa)
        session.refresh(suelta_admin)
        session.refresh(ajena)
        assert suelta_empresa.cliente_id == cliente.id and suelta_empresa.vinculo_id is None
        assert suelta_admin.cliente_id == cliente.id and suelta_admin.vinculo_id is not None
        assert ajena.cliente_id is None
        notifs = session.execute(select(Notificacion).where(Notificacion.cliente_id == cliente.id)).scalars().all()
        assert len(notifs) == 2 and any("(Administrador)" in n.titulo for n in notifs)

        # Idempotent: a second search attaches nothing more.
        assert buscar_historico(session, cliente)["sanciones_vinculadas"] == 0
    finally:
        session.close()


# --- vínculo -> cliente -------------------------------------------------------------

@pytest.mark.integration
def test_convertir_vinculo_creates_own_ficha_and_keeps_link_both_ways(clean_database):
    session = SyncSessionLocal()
    try:
        origen = _sancion(session, boe_id="BOE-A-2026-V0", nombre="Sociedad SL", identificador="B95958617")
        cliente = _cliente(session, origen, cif="B95958617")
        vinculo = VinculoCliente(
            cliente_id=cliente.id, rol="Administrador", nombre="Pepito Grillo", tipo_persona="fisica",
            identificador="2348249N", telefono="600000000", email="pepito@example.test",
        )
        session.add(vinculo)
        session.flush()
        propia = _sancion(session, boe_id="BOE-N-2026-V1", nombre="Pepito Grillo", identificador="2348249N")
        propia.cliente_id = cliente.id
        propia.vinculo_id = vinculo.id
        notif_propia = create_inapp_notification(session, propia, tipo="nueva_sancion_cliente", cliente_id=cliente.id, vinculo_id=vinculo.id)
        session.commit()
        cliente_id, vinculo_id, propia_id, notif_id = cliente.id, vinculo.id, propia.id, notif_propia.id
        origen_id = origen.id
    finally:
        session.close()

    with TestClient(app) as client:
        first = client.post(f"/api/clientes/{cliente_id}/vinculos/{vinculo_id}/convertir")
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["created"] is True
        nuevo = body["cliente"]
        assert nuevo["codigo"].startswith("CLI-") and nuevo["nombre_razon_social"] == "Pepito Grillo"
        assert nuevo["dni_nie"] == "2348249N" and nuevo["cif_nif"] is None
        assert nuevo["sancion_origen_id"] is None and nuevo["vinculo_origen_id"] == vinculo_id
        assert nuevo["telefono"] == "600000000" and nuevo["email"] == "pepito@example.test"
        assert body["vinculo"]["cliente_vinculado_id"] == nuevo["id"]

        # Idempotent.
        second = client.post(f"/api/clientes/{cliente_id}/vinculos/{vinculo_id}/convertir")
        assert second.status_code == 200 and second.json()["created"] is False and second.json()["cliente"]["id"] == nuevo["id"]

        # Appears in the directory and has its own ficha with the moved sanction.
        listado = client.get("/api/clientes", params={"search": "Pepito"}).json()
        assert [c["id"] for c in listado["items"]] == [nuevo["id"]]
        ficha = client.get(f"/api/clientes/{nuevo['id']}").json()
        assert [s["id"] for s in ficha["sanciones"]] == [propia_id]
        assert ficha["deuda_pendiente_eur"] == 120.0
        assert any(v["cliente_vinculado_id"] == cliente_id and v["rol"] == "Sociedad administrada" for v in ficha["vinculos"])
        assert any(a["tipo"] == "conversion" for a in ficha["actividades"])
        padre = client.get(f"/api/clientes/{cliente_id}").json()
        assert [s["id"] for s in padre["sanciones"]] == [origen_id]
        assert any("convertido en cliente" in a["titulo"] for a in padre["actividades"])

        # The notification now belongs to the new client.
        notifs = client.get("/api/notificaciones", params={"solo_clientes": "true"}).json()["items"]
        assert any(n["id"] == notif_id and n["cliente_id"] == nuevo["id"] and n["cliente_nombre"] == "Pepito Grillo" for n in notifs)

        # A vínculo that already points at a ficha resolves to it, name or not.
        sin_nombre = client.post(f"/api/clientes/{cliente_id}/vinculos", json={"rol": "X", "cliente_vinculado_id": nuevo["id"]}).json()
        assert client.post(f"/api/clientes/{cliente_id}/vinculos/{sin_nombre['id']}/convertir").json()["cliente"]["id"] == nuevo["id"]

    session = SyncSessionLocal()
    try:
        # Future auto-assignment routes this DNI to the new client, not to the parent.
        indice = indice_identificadores(session)
        assert indice["2348249N"] == (nuevo["id"], None)
        assert indice["B95958617"] == (cliente_id, None)
        assert session.execute(select(ActividadCliente).where(ActividadCliente.cliente_id == cliente_id)).scalars().all()
    finally:
        session.close()


@pytest.mark.integration
def test_convertir_vinculo_guesses_cif_for_companies(clean_database):
    session = SyncSessionLocal()
    try:
        origen = _sancion(session, boe_id="BOE-A-2026-V9", nombre="Matriz SA", identificador="A11111111")
        cliente = _cliente(session, origen, cif="A11111111")
        vinculo = VinculoCliente(cliente_id=cliente.id, rol="Filial", nombre="Filial SL", identificador="B77777777")
        session.add(vinculo)
        session.commit()
        ids = (cliente.id, vinculo.id)
    finally:
        session.close()
    with TestClient(app) as client:
        body = client.post(f"/api/clientes/{ids[0]}/vinculos/{ids[1]}/convertir").json()
        assert body["cliente"]["cif_nif"] == "B77777777" and body["cliente"]["dni_nie"] is None
        ficha = client.get(f"/api/clientes/{body['cliente']['id']}").json()
        assert ficha["vinculos"][0]["rol"] == "Matriz"


# --- notificaciones "solo mis clientes" ------------------------------------------------

@pytest.mark.integration
def test_solo_clientes_filter_includes_converted_and_assigned_sanctions(clean_database):
    session = SyncSessionLocal()
    try:
        convertida = _sancion(session, boe_id="BOE-A-2026-N1", nombre="Conv SL", identificador="B10000001", notificar=True)
        _sancion(session, boe_id="BOE-A-2026-N2", nombre="Suelta SL", identificador="B10000002", notificar=True)
        session.commit()
        convertida_id = convertida.id
    finally:
        session.close()

    with TestClient(app) as client:
        assert client.get("/api/notificaciones/unread-count").json() == {"count": 2, "count_clientes": 0}
        cliente = client.post(f"/api/sanciones/{convertida_id}/convertir").json()["cliente"]
        assert client.get("/api/notificaciones/unread-count").json() == {"count": 2, "count_clientes": 1}
        solo = client.get("/api/notificaciones", params={"solo_clientes": "true"}).json()
        assert solo["total"] == 1
        assert solo["items"][0]["sancionado_id"] == convertida_id
        assert solo["items"][0]["cliente_id"] == cliente["id"] and solo["items"][0]["cliente_nombre"] == "Conv SL"
        todas = client.get("/api/notificaciones").json()
        assert todas["total"] == 2 and {n["cliente_id"] for n in todas["items"]} == {cliente["id"], None}


# --- configuración -------------------------------------------------------------------

@pytest.mark.integration
def test_configuracion_round_trips_and_reports_env_gates(clean_database, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "openai_extraction_enabled", False)
    with TestClient(app) as client:
        inicial = client.get("/api/configuracion").json()
        assert inicial["configuracion"]["extraccion_modo"] == "tiempo_real"
        assert inicial["configuracion"]["extraccion_automatica"] is True
        assert inicial["configuracion"]["historico_extraccion_modo"] == "batch"
        assert inicial["entorno"]["openai_extraccion_disponible"] is False
        assert "OPENAI_EXTRACTION_ENABLED" in inicial["entorno"]["openai_extraccion_motivo"]

        cambiado = client.put("/api/configuracion", json={"extraccion_modo": "batch", "teu_max_por_ejecucion": 50}).json()
        assert cambiado["configuracion"]["extraccion_modo"] == "batch"
        assert cambiado["configuracion"]["teu_max_por_ejecucion"] == 50
        assert cambiado["configuracion"]["extraccion_automatica"] is True  # untouched
        assert client.get("/api/configuracion").json()["configuracion"]["extraccion_modo"] == "batch"

        assert client.put("/api/configuracion", json={"extraccion_modo": "ahora_mismo"}).status_code == 422
        assert client.put("/api/configuracion", json={"desconocido": 1}).status_code == 422
        assert client.put("/api/configuracion", json={"extraccion_max_docs_por_ejecucion": -1}).status_code == 422
