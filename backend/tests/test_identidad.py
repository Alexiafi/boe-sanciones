"""One person, one record: a notice of a known DNI/CIF shows who it is, inherits
what is known, and edits are shared across all notices of that party."""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.database import SyncSessionLocal
from app.main import app
from app.models.cliente import ActividadCliente, Cliente, VinculoCliente
from app.models.documento import BoeDocumento
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.models.seguimiento import Seguimiento
from app.services.extractor import AfectadoExtraido, ResultadoExtraccion
from app.services.historico.patterns import clave_identidad
from app.tasks import scraping

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


# --- the key itself (no database needed) ------------------------------------

@pytest.mark.parametrize("valor,esperado", [
    ("12345678Z", "12345678Z"), ("12.345.678-z", "12345678Z"), (" b 12345678 ", "B12345678"),
    ("X1234567L", "X1234567L"), ("A58818501", "A58818501"),
    # Never a key: masked, partial, free text.
    ("***4567**", None), ("4567", None), ("NO CONSTA", None), ("", None), (None, None), ("A-1", None),
])
def test_clave_identidad_only_for_complete_document_numbers(valor, esperado):
    assert clave_identidad(valor) == esperado


# --- helpers ----------------------------------------------------------------

_contador = {"n": 0}


def _notice(session, *, identificador="12345678Z", nombre=None, dia=1, estado="nueva", **extra) -> Sancionado:
    _contador["n"] += 1
    n = _contador["n"]
    doc = BoeDocumento(boe_id=f"BOE-ID-{n}", fecha_publicacion=date(2026, 8, dia), titulo=f"Aviso {n}")
    session.add(doc)
    session.flush()
    fila = Sancionado(
        boe_document_id=doc.id, codigo=f"OP-2026-{n:06d}", origen_clave=f"id-clave-{n}".ljust(64, "x")[:64],
        nombre=nombre, identificador=identificador, estado_oportunidad=estado, **extra,
    )
    session.add(fila)
    session.flush()
    return fila


def _cliente(session, *, cif=None, dni=None, nombre="Acme Logistica SL", estado="activo", **extra) -> Cliente:
    _contador["n"] += 1
    cliente = Cliente(
        codigo=f"CLI-2026-{_contador['n']:04d}", nombre_razon_social=nombre,
        cif_nif=cif, dni_nie=dni, estado_cliente=estado, **extra,
    )
    session.add(cliente)
    session.flush()
    return cliente


def _extractor(identificador, nombre=None, **extra):
    return lambda texto, titulo: ResultadoExtraccion(
        afectados=[AfectadoExtraido(identificador=identificador, nombre=nombre, **extra)]
    )


def _deps(documentos, extractor):
    return scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documentos,
        fetch_text=lambda d: (f"texto de {d['identificador']}", "xml", None), extractor=extractor,
        send_digest=lambda *_: None, notify=scraping.create_inapp_notification,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )


@pytest.fixture
def pipeline_abierto(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_extraction_max_documents_per_run", 50)


def _documento(boe_id: str, dia: int) -> list[dict]:
    return [{"identificador": boe_id, "fecha_publicacion": date(2026, 9, dia), "titulo": "TEU", "seccion_codigo": "3"}]


# --- arrival of a new notice (pipeline) ---------------------------------------

@pytest.mark.integration
def test_new_notice_of_a_client_shows_the_clients_name_and_alerts_once(pipeline_abierto, clean_database):
    """A TEU notice carries only the CIF. It must come out attached to the
    client, under the client's name, with ONE alert (it used to be announced
    first as "Desconocido" and then again for the client)."""
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678", telefono="611222333", email="info@acme.test", localidad="Sevilla")
    session.commit()
    cliente_id = cliente.id
    session.close()

    resultado = scraping.run_scraping(
        "2026-09-20", permitir_extraccion_pago=True,
        dependencies=_deps(_documento("BOE-N-2026-1", 20), _extractor("B12345678", importe_multa_eur=200)),
    )
    assert resultado["extracted"] == 1 and resultado["clientes_asignados"] == 1

    session = SyncSessionLocal()
    try:
        fila = session.execute(select(Sancionado)).scalars().one()
        assert fila.cliente_id == cliente_id and fila.estado_oportunidad == "cliente"
        assert fila.nombre == "Acme Logistica SL"          # inherited: the notice had none
        assert fila.telefono == "611222333" and fila.localidad == "Sevilla"
        alertas = session.execute(select(Notificacion)).scalars().all()
        assert len(alertas) == 1
        assert alertas[0].tipo == "nueva_sancion_cliente" and alertas[0].cliente_id == cliente_id
        assert "Acme Logistica SL" in alertas[0].titulo and "Desconocido" not in alertas[0].titulo
    finally:
        session.close()


@pytest.mark.integration
def test_new_notice_inherits_name_and_contact_found_for_the_same_dni(pipeline_abierto, clean_database):
    """Not a client yet: a new notice of a DNI already worked arrives with the
    contact found before — Judit does not search (or call) from zero again."""
    session = SyncSessionLocal()
    previa = _notice(
        session, identificador="12345678Z", nombre="Juan Perez Garcia", dia=1, estado="contactada",
        telefono="611222333", email="juan@perez.test", localidad="Sevilla",
        contacto_estado="manual", contacto_fuente="manual",
    )
    session.commit()
    previa_id = previa.id
    session.close()

    scraping.run_scraping(
        "2026-09-21", permitir_extraccion_pago=True,
        dependencies=_deps(_documento("BOE-N-2026-2", 21), _extractor("12.345.678-Z")),
    )

    session = SyncSessionLocal()
    try:
        nueva = session.execute(select(Sancionado).where(Sancionado.id != previa_id)).scalars().one()
        assert nueva.identidad_clave == "12345678Z"
        assert nueva.nombre == "Juan Perez Garcia" and nueva.telefono == "611222333"
        assert nueva.email == "juan@perez.test" and nueva.localidad == "Sevilla"
        assert nueva.contacto_estado == "manual"      # the provenance travels with the contact
        assert nueva.estado_oportunidad == "nueva"    # a new fine is a new chance: flagged, not hidden
        assert nueva.cliente_id is None
    finally:
        session.close()


@pytest.mark.integration
def test_phone_and_email_copied_by_the_extraction_are_never_stored(pipeline_abierto, clean_database):
    """The notice's only phone/email is the issuing office's: the pipeline must
    not store it as the sanctioned person's (it did, for 1,481 people)."""
    scraping.run_scraping(
        "2026-09-24", permitir_extraccion_pago=True,
        dependencies=_deps(
            _documento("BOE-N-2026-9", 24),
            _extractor("12345678Z", telefono="942 751 245", email="multas@ayto-reinosa.test", localidad="Reinosa"),
        ),
    )
    session = SyncSessionLocal()
    try:
        fila = session.execute(select(Sancionado)).scalars().one()
        assert fila.telefono is None and fila.email is None and fila.contacto_estado == "pendiente"
        assert fila.localidad == "Reinosa"
    finally:
        session.close()


@pytest.mark.integration
def test_masked_identifiers_are_never_merged(pipeline_abierto, clean_database):
    session = SyncSessionLocal()
    _notice(session, identificador="***4567**", nombre="Ana Lopez", telefono="611000111")
    session.commit()
    session.close()
    scraping.run_scraping(
        "2026-09-22", permitir_extraccion_pago=True,
        dependencies=_deps(_documento("BOE-N-2026-3", 22), _extractor("***4567**", nombre="Otra Persona")),
    )
    session = SyncSessionLocal()
    try:
        nueva = session.execute(select(Sancionado).where(Sancionado.nombre == "Otra Persona")).scalars().one()
        assert nueva.identidad_clave is None and nueva.telefono is None
    finally:
        session.close()


@pytest.mark.integration
def test_a_vinculo_identifier_attaches_the_notice_to_the_parent_client(pipeline_abierto, clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678")
    vinculo = VinculoCliente(
        cliente_id=cliente.id, rol="Administrador", nombre="Luis Admin", identificador="87654321X", tipo_persona="fisica",
    )
    session.add(vinculo)
    session.commit()
    cliente_id, vinculo_id = cliente.id, vinculo.id
    session.close()
    scraping.run_scraping(
        "2026-09-23", permitir_extraccion_pago=True,
        dependencies=_deps(_documento("BOE-N-2026-4", 23), _extractor("87654321X")),
    )
    session = SyncSessionLocal()
    try:
        fila = session.execute(select(Sancionado)).scalars().one()
        assert fila.cliente_id == cliente_id and fila.vinculo_id == vinculo_id and fila.nombre == "Luis Admin"
        alerta = session.execute(select(Notificacion)).scalars().one()
        assert "Luis Admin" in alerta.titulo and "Administrador" in alerta.titulo
    finally:
        session.close()


# --- manual edits (API) -------------------------------------------------------

@pytest.mark.integration
def test_editing_a_notice_shares_the_change_with_the_others_and_the_client(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, dni="12345678Z", nombre="Juan Perez Garcia", estado="informado")
    uno = _notice(session, identificador="12345678Z", nombre="Juan Perez Garcia", dia=1, cliente_id=cliente.id, estado="cliente")
    dos = _notice(session, identificador="12345678Z", nombre=None, dia=2, web="https://juan.test")
    otro = _notice(session, identificador="99999999R", nombre="Otro", dia=3)
    session.commit()
    uno_id, dos_id, otro_id, cliente_id = uno.id, dos.id, otro.id, cliente.id
    session.close()

    with TestClient(app) as client:
        resp = client.patch(f"/api/sanciones/{uno_id}", json={
            "telefono": "611 222 333", "email": "juan@perez.test", "localidad": "Sevilla", "web": None,
        })
        assert resp.status_code == 200, resp.text

    session = SyncSessionLocal()
    try:
        dos = session.get(Sancionado, dos_id)
        assert dos.telefono == "611 222 333" and dos.email == "juan@perez.test" and dos.localidad == "Sevilla"
        assert dos.web == "https://juan.test"   # `web` was not changed on the edited notice (it had none): untouched
        assert dos.contacto_estado == "manual"
        assert session.get(Sancionado, otro_id).telefono is None      # another party: untouched
        cliente = session.get(Cliente, cliente_id)
        assert cliente.telefono == "611 222 333" and cliente.email == "juan@perez.test" and cliente.localidad == "Sevilla"
    finally:
        session.close()


@pytest.mark.integration
def test_clearing_a_value_on_the_edited_notice_clears_it_everywhere(clean_database):
    session = SyncSessionLocal()
    uno = _notice(session, identificador="12345678Z", nombre="Juan", dia=1, telefono="600000000")
    dos = _notice(session, identificador="12345678Z", nombre="Juan", dia=2, telefono="600000000")
    session.commit()
    uno_id, dos_id = uno.id, dos.id
    session.close()
    with TestClient(app) as client:
        assert client.patch(f"/api/sanciones/{uno_id}", json={"telefono": None}).status_code == 200
    session = SyncSessionLocal()
    try:
        assert session.get(Sancionado, dos_id).telefono is None     # a wrong number removed once, not N times
    finally:
        session.close()


@pytest.mark.integration
def test_saving_without_changing_a_field_never_wipes_the_siblings_value(clean_database):
    """The form sends every field on each save: a blank web on this notice must
    not erase the web another notice of the same person has."""
    session = SyncSessionLocal()
    uno = _notice(session, identificador="12345678Z", nombre="Juan", dia=1)
    dos = _notice(session, identificador="12345678Z", nombre="Juan", dia=2, web="https://juan.test", telefono="611222333")
    session.commit()
    uno_id, dos_id = uno.id, dos.id
    session.close()

    with TestClient(app) as client:
        resp = client.patch(f"/api/sanciones/{uno_id}", json={
            "nombre": "Juan", "web": None, "telefono": None, "email": None, "estado_oportunidad": "revisada",
        })
        assert resp.status_code == 200
        assert resp.json()["contacto_estado"] == "pendiente"      # a no-op save is not a "manual" confirmation
    session = SyncSessionLocal()
    try:
        dos = session.get(Sancionado, dos_id)
        assert dos.web == "https://juan.test" and dos.telefono == "611222333"
    finally:
        session.close()


@pytest.mark.integration
def test_marking_contacted_closes_the_other_open_notices_of_that_party(clean_database):
    session = SyncSessionLocal()
    uno = _notice(session, identificador="12345678Z", nombre="Juan", dia=1)
    abierta = _notice(session, identificador="12345678Z", nombre="Juan", dia=2, estado="revisada")
    descartada = _notice(session, identificador="12345678Z", nombre="Juan", dia=3, estado="descartada")
    otra_persona = _notice(session, identificador="99999999R", nombre="Otro", dia=4)
    session.commit()
    ids = (uno.id, abierta.id, descartada.id, otra_persona.id)
    session.close()
    with TestClient(app) as client:
        assert client.patch(f"/api/sanciones/{ids[0]}", json={"estado_oportunidad": "contactada"}).status_code == 200
    session = SyncSessionLocal()
    try:
        assert session.get(Sancionado, ids[1]).estado_oportunidad == "contactada"
        assert session.get(Sancionado, ids[2]).estado_oportunidad == "descartada"   # a decision already taken stays
        assert session.get(Sancionado, ids[3]).estado_oportunidad == "nueva"
    finally:
        session.close()


@pytest.mark.integration
def test_client_ficha_edits_reach_the_clients_notices_but_not_its_vinculos(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678")
    vinculo = VinculoCliente(cliente_id=cliente.id, rol="Administrador", nombre="Luis", identificador="87654321X")
    session.add(vinculo)
    session.flush()
    propia = _notice(session, identificador="B12345678", dia=1, cliente_id=cliente.id, estado="cliente")
    del_admin = _notice(
        session, identificador="87654321X", nombre="Luis", dia=2, cliente_id=cliente.id, vinculo_id=vinculo.id, estado="cliente",
    )
    session.commit()
    cliente_id, propia_id, admin_id = cliente.id, propia.id, del_admin.id
    session.close()
    with TestClient(app) as client:
        resp = client.patch(f"/api/clientes/{cliente_id}", json={"telefono": "933 444 555", "localidad": "Girona"})
        assert resp.status_code == 200
    session = SyncSessionLocal()
    try:
        assert session.get(Sancionado, propia_id).telefono == "933 444 555"
        assert session.get(Sancionado, propia_id).localidad == "Girona"
        assert session.get(Sancionado, admin_id).telefono is None
    finally:
        session.close()


# --- conversion / client created ----------------------------------------------

@pytest.mark.integration
def test_converting_a_notice_attaches_every_earlier_notice_of_that_party(clean_database):
    session = SyncSessionLocal()
    elegida = _notice(
        session, identificador="12345678Z", nombre="Juan Perez", dia=3, tipo_persona="fisica", tipo_identificador="DNI",
    )
    antigua = _notice(session, identificador="12345678Z", dia=1, estado="contactada")
    otra = _notice(session, identificador="99999999R", nombre="Otro", dia=2)
    alerta = Notificacion(tipo="nueva_sancion", titulo="x", sancionado_id=antigua.id)
    session.add(alerta)
    session.commit()
    ids = (elegida.id, antigua.id, otra.id, alerta.id)
    session.close()
    with TestClient(app) as client:
        resp = client.post(f"/api/sanciones/{ids[0]}/convertir")
        assert resp.status_code == 200
        cliente_id = resp.json()["cliente"]["id"]
    session = SyncSessionLocal()
    try:
        antigua = session.get(Sancionado, ids[1])
        assert antigua.cliente_id == cliente_id and antigua.estado_oportunidad == "cliente"
        assert session.get(Sancionado, ids[2]).cliente_id is None
        assert session.get(Notificacion, ids[3]).cliente_id == cliente_id
    finally:
        session.close()


@pytest.mark.integration
def test_typing_a_clients_dni_attaches_its_notices(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, cif=None, dni=None, nombre="Persona Sin Dni")
    antes = _notice(session, identificador="12345678Z", nombre="Persona Sin Dni", dia=1)
    session.commit()
    cliente_id, antes_id = cliente.id, antes.id
    session.close()
    with TestClient(app) as client:
        assert client.patch(f"/api/clientes/{cliente_id}", json={"dni_nie": "12.345.678-z"}).status_code == 200
    session = SyncSessionLocal()
    try:
        assert session.get(Sancionado, antes_id).cliente_id == cliente_id
    finally:
        session.close()


# --- listing and detail ---------------------------------------------------------

@pytest.mark.integration
def test_panel_search_by_dni_covers_all_dates_and_any_formatting(clean_database):
    session = SyncSessionLocal()
    vieja = _notice(session, identificador="12345678Z", nombre=None, dia=1)
    session.execute(text("UPDATE boe_documentos SET fecha_publicacion = '2023-02-01'"))
    session.commit()
    vieja_id = vieja.id
    session.close()
    with TestClient(app) as client:
        # No dates: the default 30-day window would hide it.
        for consulta in ("12345678Z", "12.345.678-z", "12345678", "  12345678z "):
            items = client.get("/api/sanciones", params={"search": consulta}).json()["items"]
            assert [i["id"] for i in items] == [vieja_id], consulta
        assert client.get("/api/sanciones").json()["items"] == []     # without a search: last 30 days only


@pytest.mark.integration
def test_listing_shows_the_client_the_history_and_filters_on_both(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678", nombre="Acme Logistica SL")
    de_cliente = _notice(
        session, identificador="B12345678", nombre=None, dia=1, cliente_id=cliente.id, estado="cliente", telefono="611222333",
    )
    llamado_antes = _notice(session, identificador="12345678Z", nombre="Juan", dia=2, estado="contactada")
    nuevo_de_llamado = _notice(session, identificador="12345678Z", nombre=None, dia=3)
    limpio = _notice(session, identificador="99999999R", nombre="Otro", dia=4)
    session.commit()
    ids = dict(cliente=de_cliente.id, llamado=llamado_antes.id, nuevo=nuevo_de_llamado.id, limpio=limpio.id)
    session.close()

    with TestClient(app) as client:
        def buscar(**params):
            base = {"fecha_desde": "2026-01-01", "fecha_hasta": "2026-12-31", "page_size": 100}
            return {i["id"]: i for i in client.get("/api/sanciones", params={**base, **params}).json()["items"]}

        todas = buscar()
        item = todas[ids["cliente"]]
        assert item["nombre_mostrado"] == "Acme Logistica SL" and item["cliente_nombre"] == "Acme Logistica SL"
        assert item["cliente_estado"] == "activo"
        nuevo = todas[ids["nuevo"]]
        assert nuevo["nombre_mostrado"] == "12345678Z" and nuevo["ya_contactado"] is True and nuevo["otras_notificaciones"] == 1
        assert todas[ids["limpio"]]["ya_contactado"] is False

        assert set(buscar(es_cliente="true")) == {ids["cliente"]}
        assert ids["cliente"] not in buscar(es_cliente="false")
        assert set(buscar(gestion_previa="true")) == {ids["nuevo"]}
        assert ids["nuevo"] not in buscar(gestion_previa="false")
        assert set(buscar(solo_con_telefono="true")) == {ids["cliente"]}
        assert set(buscar(search="acme")) == {ids["cliente"]}       # also by the client's name


@pytest.mark.integration
def test_detail_lists_the_other_notices_and_their_notes(clean_database):
    session = SyncSessionLocal()
    actual = _notice(session, identificador="12345678Z", nombre=None, dia=3)
    previa = _notice(session, identificador="12345678Z", nombre="Juan", dia=1, estado="contactada")
    ajena = _notice(session, identificador="99999999R", nombre="Otro", dia=2)
    session.add(Seguimiento(sancionado_id=previa.id, nota="Llamado el lunes, pide que le escriban", estado="pendiente"))
    session.add(Seguimiento(sancionado_id=ajena.id, nota="no es de este", estado="pendiente"))
    session.commit()
    actual_id, previa_id = actual.id, previa.id
    session.close()
    with TestClient(app) as client:
        detalle = client.get(f"/api/sanciones/{actual_id}").json()
    assert detalle["ya_contactado"] is True and detalle["notas_del_titular"] == 1
    assert [r["id"] for r in detalle["relacionadas"]] == [previa_id]
    assert detalle["relacionadas"][0]["ultima_nota"] == "Llamado el lunes, pide que le escriban"
    assert [n["nota"] for n in detalle["seguimientos_relacionados"]] == ["Llamado el lunes, pide que le escriban"]


@pytest.mark.integration
def test_notification_titles_use_what_is_known_now(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678", nombre="Acme Logistica SL")
    fila = _notice(session, identificador="B12345678", nombre=None, cliente_id=cliente.id, estado="cliente")
    sin_nombre = _notice(session, identificador="12345678Z", nombre=None, dia=2)
    session.add(Notificacion(tipo="nueva_sancion", titulo="Nueva sanción: Desconocido", sancionado_id=fila.id))
    session.add(Notificacion(tipo="nueva_sancion", titulo="Nueva sanción: Desconocido", sancionado_id=sin_nombre.id))
    session.commit()
    session.close()
    with TestClient(app) as client:
        titulos = {n["titulo"] for n in client.get("/api/notificaciones").json()["items"]}
    assert titulos == {"Nueva sanción de cliente: Acme Logistica SL", "Nueva sanción: 12345678Z"}


# --- clients with no DNI/CIF on file: recognised by exact, distinctive name -----

@pytest.mark.integration
def test_a_client_without_a_number_is_recognised_by_its_exact_distinctive_name(pipeline_abierto, clean_database):
    """Two of the seven clients of a real database had no DNI/CIF (converted
    from a masked or name-only notice): their new notices could never match."""
    session = SyncSessionLocal()
    empresa = _cliente(session, cif=None, nombre="HIERROS Y ACEROS DE MALLORCA, SA", telefono="971 43 11 00")
    persona = _cliente(session, cif=None, nombre="Joyce Magdalena Braaf")
    homonimo = _cliente(session, cif=None, nombre="Juan Garcia")        # two words: too common to match on
    con_numero = _cliente(session, cif="B12345678", nombre="Acme Logistica SL")
    session.commit()
    ids = dict(empresa=empresa.id, persona=persona.id, homonimo=homonimo.id, con_numero=con_numero.id)
    session.close()

    def extractor(texto, titulo):
        return ResultadoExtraccion(afectados=[
            AfectadoExtraido(nombre="Hierros y Aceros de Mallorca S.A.", identificador="***1234**"),
            AfectadoExtraido(nombre="JOYCE MAGDALENA BRAAF", identificador=None, importe_multa_eur=90),
            AfectadoExtraido(nombre="Juan Garcia", identificador="***9999**"),
            # the same name as a client WITH a number is not matched by name: its number is what identifies it
            AfectadoExtraido(nombre="Acme Logistica SL", identificador="***5555**"),
        ])

    resultado = scraping.run_scraping(
        "2026-09-25", permitir_extraccion_pago=True, dependencies=_deps(_documento("BOE-2026-N1", 25), extractor),
    )
    assert resultado["extracted"] == 4 and resultado["clientes_asignados"] == 2

    session = SyncSessionLocal()
    try:
        filas = {s.nombre: s for s in session.execute(select(Sancionado)).scalars().all()}
        assert filas["Hierros y Aceros de Mallorca S.A."].cliente_id == ids["empresa"]
        assert filas["Hierros y Aceros de Mallorca S.A."].telefono == "971 43 11 00"      # inherited from the ficha
        assert filas["JOYCE MAGDALENA BRAAF"].cliente_id == ids["persona"]
        assert filas["Juan Garcia"].cliente_id is None
        assert filas["Acme Logistica SL"].cliente_id is None
        actividad = session.execute(select(ActividadCliente).where(ActividadCliente.cliente_id == ids["empresa"])).scalars().one()
        assert "nombre" in actividad.detalle and "verifícalo" in actividad.detalle
        alertas = {a.cliente_id for a in session.execute(select(Notificacion)).scalars().all() if a.cliente_id}
        assert alertas == {ids["empresa"], ids["persona"]}
    finally:
        session.close()


@pytest.mark.integration
def test_giving_a_client_a_name_only_links_earlier_notices_with_that_exact_name(clean_database):
    session = SyncSessionLocal()
    previa = _notice(session, identificador=None, nombre="Hierros y Aceros de Mallorca S.A.", dia=1)
    otra = _notice(session, identificador=None, nombre="Hierros del Norte SA", dia=2)
    con_numero = _notice(session, identificador="B12345678", nombre="Hierros y Aceros de Mallorca S.A.", dia=3)
    cliente = _cliente(session, cif=None, nombre="HIERROS Y ACEROS DE MALLORCA, SA")
    session.commit()
    ids = (previa.id, otra.id, con_numero.id, cliente.id)
    session.close()

    from app.database import async_session_factory
    from app.services.identidad import vincular_sanciones_a_cliente
    import asyncio

    async def correr():
        async with async_session_factory() as db:
            cliente = await db.get(Cliente, ids[3])
            vinculadas = await vincular_sanciones_a_cliente(db, cliente)
            await db.commit()
            return vinculadas

    assert asyncio.run(correr()) == 1
    session = SyncSessionLocal()
    try:
        assert session.get(Sancionado, ids[0]).cliente_id == ids[3]
        assert session.get(Sancionado, ids[1]).cliente_id is None       # a different company
        assert session.get(Sancionado, ids[2]).cliente_id is None       # has its own number: not ours to take by name
    finally:
        session.close()


@pytest.mark.parametrize("nombre,esperado", [
    ("HIERROS Y ACEROS DE MALLORCA, SA", "HIERROS Y ACEROS DE MALLORCA SA"),
    ("Tarianet, S.L.", "TARIANET SL"),
    ("Joyce Magdalena Braaf", "JOYCE MAGDALENA BRAAF"),
    ("Juan Garcia", None), ("Pérez", None), ("", None), (None, None), ("Acme", None),
])
def test_distinctive_names_only(nombre, esperado):
    from app.services.identidad import nombre_clave

    assert nombre_clave(nombre) == esperado


@pytest.mark.integration
def test_address_fields_are_validated_and_a_name_equal_to_the_dni_is_not_a_name(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678", nombre="Acme Logistica SL")
    # the extraction sometimes puts the identifier itself in the name field
    fila = _notice(session, identificador="B12345678", nombre="B12345678", cliente_id=cliente.id, estado="cliente")
    session.commit()
    fila_id = fila.id
    session.close()
    with TestClient(app) as client:
        assert client.patch(f"/api/sanciones/{fila_id}", json={"codigo_postal": "123456789012"}).status_code == 422
        ok = client.patch(f"/api/sanciones/{fila_id}", json={"direccion": " Calle Falsa 1 ", "localidad": "Girona", "codigo_postal": "17001"})
        assert ok.status_code == 200 and ok.json()["direccion"] == "Calle Falsa 1"
        assert client.get(f"/api/sanciones/{fila_id}").json()["nombre_mostrado"] == "Acme Logistica SL"


@pytest.mark.integration
def test_a_clients_notice_can_be_saved_with_its_current_state(clean_database):
    """The edit form sends the state back on every save. For a notice that
    belongs to a client that is "cliente", which the PATCH used to reject (422):
    none of the notices of a client could be edited — data typed on them
    "was not saved"."""
    session = SyncSessionLocal()
    cliente = _cliente(session, cif="B12345678")
    suyo = _notice(session, identificador="B12345678", cliente_id=cliente.id, estado="cliente")
    ajeno = _notice(session, identificador="99999999R", dia=2)
    session.commit()
    suyo_id, ajeno_id = suyo.id, ajeno.id
    session.close()
    with TestClient(app) as client:
        ok = client.patch(f"/api/sanciones/{suyo_id}", json={"estado_oportunidad": "cliente", "telefono": "933 444 555"})
        assert ok.status_code == 200 and ok.json()["estado_oportunidad"] == "cliente" and ok.json()["telefono"] == "933 444 555"
        # but a notice cannot be made a client's by hand
        assert client.patch(f"/api/sanciones/{ajeno_id}", json={"estado_oportunidad": "cliente"}).status_code == 422
