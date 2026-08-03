"""Client history search: exact JSONB match + FTS by normalised name.
Idempotency and non-regression of prior extraction/estado on re-search."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.database import SyncSessionLocal
from app.models.cliente import Cliente
from app.models.historico import HistoricoDoc, HistoricoResultado
from app.services.historico.busqueda import buscar_historico, claves_de_cliente, consultar_historico
from app.services.historico.indexado import upsert_historico_doc
from app.services.historico.patterns import extraer_claves
from app.services.oportunidades import allocate_codigo

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _cliente(session, **overrides) -> Cliente:
    from app.models.documento import BoeDocumento
    from app.models.sancionado import Sancionado

    doc = BoeDocumento(boe_id=f"BOE-BUSQ-{overrides.get('sufijo', '1')}", fecha_publicacion=date(2026, 7, 1), titulo="Origen")
    session.add(doc)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
        origen_clave=f"clave-{overrides.get('sufijo', '1')}", nombre=overrides.get("nombre", "Acme Logistica SL"),
    )
    session.add(sancionado)
    session.flush()
    cliente = Cliente(
        codigo=f"CLI-2026-{overrides.get('sufijo', '1')}",
        nombre_razon_social=overrides.get("nombre", "Acme Logistica SL"),
        cif_nif=overrides.get("cif_nif"), dni_nie=overrides.get("dni_nie"),
        matriculas=overrides.get("matriculas", []), sancion_origen_id=sancionado.id,
    )
    session.add(cliente)
    session.flush()
    return cliente


def _doc(session, boe_id: str, texto: str, titulo: str = "Doc", fecha=None) -> HistoricoDoc:
    claves = extraer_claves(texto, titulo)
    doc, _ = upsert_historico_doc(
        session, boe_id=boe_id, fuente="boe", fecha_publicacion=fecha or date(2026, 1, 1),
        titulo=titulo, origen_indexado="backfill", texto=texto, claves=claves,
    )
    return doc


@pytest.mark.integration
def test_match_exacto_por_cif_dni_y_matricula(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, sufijo="1", cif_nif="B12345674", dni_nie=None, matriculas=["1234BCD"])
        _doc(session, "BOE-BUSQ-D1", "Sancionada ACME LOGISTICA SL con CIF B12345674.")
        _doc(session, "BOE-BUSQ-D2", "Vehículo con matrícula 1234 BCD embargado.")
        session.commit()

        resultado = buscar_historico(session, cliente)
        vias = {r.via_match for r in resultado["resultados"]}
        assert "cif" in vias
        assert "matricula" in vias
        assert len(resultado["resultados"]) == 2
    finally:
        session.close()


@pytest.mark.integration
def test_fts_por_nombre_ignora_acentos_y_mayusculas(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, sufijo="2", nombre="José María García")
        _doc(
            session, "BOE-BUSQ-D3",
            "Notificado a JOSE MARIA GARCIA con DNI 12345678Z por infracción.",
            titulo="JOSE MARIA GARCIA notificado",
        )
        session.commit()

        resultado = buscar_historico(session, cliente)
        assert len(resultado["resultados"]) == 1
        assert resultado["resultados"][0].via_match in ("nombre", "nombre_dni_parcial")
    finally:
        session.close()


@pytest.mark.integration
def test_sentinela_impide_cruce_entre_nombres(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, sufijo="3", nombre="Lopez Pedro")
        # Two DIFFERENT people in the same document; the search name must not
        # match by concatenating "Ana Lopez" with "Pedro Martin".
        _doc(session, "BOE-BUSQ-D4", "Sancionados: ANA LOPEZ y PEDRO MARTIN.", titulo="ANA LOPEZ PEDRO MARTIN")
        session.commit()

        resultado = buscar_historico(session, cliente)
        assert resultado["resultados"] == []
    finally:
        session.close()


@pytest.mark.integration
def test_resultados_idempotentes_no_pisan_extraccion(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, sufijo="4", cif_nif="B12345674")
        _doc(session, "BOE-BUSQ-D5", "Sancionada ACME LOGISTICA SL con CIF B12345674.")
        session.commit()

        primero = buscar_historico(session, cliente)
        assert len(primero["resultados"]) == 1
        resultado_id = primero["resultados"][0].id

        # Simulate prior on-demand extraction work + a manual estado decision.
        row = session.get(HistoricoResultado, resultado_id)
        row.extraido = True
        row.datos_extraidos = {"nombre": "Acme"}
        row.estado = "confirmado"
        session.commit()

        segundo = buscar_historico(session, cliente)
        assert len(segundo["resultados"]) == 1
        row_after = session.get(HistoricoResultado, resultado_id)
        assert row_after.extraido is True
        assert row_after.datos_extraidos == {"nombre": "Acme"}
        assert row_after.estado == "confirmado"
    finally:
        session.close()


@pytest.mark.integration
def test_sin_coincidencias_devuelve_vacio(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, sufijo="5", cif_nif="A99999999")
        session.commit()
        resultado = buscar_historico(session, cliente)
        assert resultado["resultados"] == []
        assert resultado["avisos"]  # always carries the TEU limitation notice
    finally:
        session.close()


@pytest.mark.integration
def test_consulta_es_de_solo_lectura(clean_database):
    session = SyncSessionLocal()
    try:
        _doc(session, "BOE-BUSQ-D6", "Sancionada ACME LOGISTICA SL con CIF B12345674.")
        session.commit()

        resultado = consultar_historico(session, cif="B12345674")
        assert len(resultado["resultados"]) == 1
        # No cliente_id exists for a bare consulta -> nothing persisted.
        assert session.execute(select(HistoricoResultado)).scalars().all() == []
    finally:
        session.close()


def test_claves_de_cliente_normaliza():
    class FakeCliente:
        cif_nif = "b-1234567-4"
        dni_nie = None
        matriculas = ["1234-bcd"]
        nombre_razon_social = "José García"

    claves = claves_de_cliente(FakeCliente())
    assert claves.identificadores == ["B12345674"]
    assert claves.matriculas == ["1234BCD"]
    assert claves.nombre_norm == "JOSE GARCIA"
