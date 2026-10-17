"""Client management Judit reported as broken: deleting a client, keeping
information-only prospects apart from real clients, and scheduling actions
(a "tarea" used to fail with a 500; there was no date and no agenda view)."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.main import app
from app.models.cliente import AccionAgendada, ActividadCliente, Cliente, NotaCliente, VinculoCliente
from app.models.documento import BoeDocumento
from app.models.documentos_comerciales import DocumentoComercial
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.services.documentos_comerciales import generar_contrato, generar_factura, nombre_fichero_seguro

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")

_n = {"v": 0}


def _cliente(session, **extra) -> Cliente:
    _n["v"] += 1
    valores = dict(
        codigo=f"CLI-2026-{_n['v']:04d}", nombre_razon_social=f"Cliente {_n['v']} SL", cif_nif=f"B1234567{_n['v'] % 10}",
        direccion_fiscal="Calle Falsa 123, Madrid",
    )
    valores.update(extra)
    cliente = Cliente(**valores)
    session.add(cliente)
    session.flush()
    return cliente


def _notice(session, cliente=None, **extra) -> Sancionado:
    _n["v"] += 1
    doc = BoeDocumento(boe_id=f"BOE-GES-{_n['v']}", fecha_publicacion=date(2026, 8, 1), titulo="Aviso")
    session.add(doc)
    session.flush()
    fila = Sancionado(
        boe_document_id=doc.id, codigo=f"OP-2026-{_n['v']:06d}", origen_clave=f"ges-{_n['v']}".ljust(64, "x")[:64],
        identificador=extra.pop("identificador", "B12345678"),
        cliente_id=cliente.id if cliente else None,
        estado_oportunidad="cliente" if cliente else "nueva", **extra,
    )
    session.add(fila)
    session.flush()
    return fila


# --- delete ------------------------------------------------------------------

@pytest.mark.integration
def test_a_client_can_be_deleted_and_its_notices_go_back_to_the_panel(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, estado_cliente="informado")
    aviso = _notice(session, cliente)
    alerta = Notificacion(tipo="nueva_sancion_cliente", titulo="x", sancionado_id=aviso.id, cliente_id=cliente.id)
    session.add_all([
        alerta, NotaCliente(cliente_id=cliente.id, texto="nota"),
        ActividadCliente(cliente_id=cliente.id, tipo="sistema", titulo="act"),
        AccionAgendada(cliente_id=cliente.id, tipo="llamada", titulo="llamar"),
        VinculoCliente(cliente_id=cliente.id, rol="Administrador", nombre="Luis"),
    ])
    # Another client pointing at this ficha keeps the person as a plain link.
    otro = _cliente(session)
    session.add(VinculoCliente(cliente_id=otro.id, cliente_vinculado_id=cliente.id, rol="Filial", identificador=cliente.cif_nif))
    session.commit()
    cliente_id, aviso_id, alerta_id, otro_id = cliente.id, aviso.id, alerta.id, otro.id
    nombre = cliente.nombre_razon_social
    session.close()

    with TestClient(app) as client:
        sin_confirmar = client.delete(f"/api/clientes/{cliente_id}")
        assert sin_confirmar.status_code == 422                     # explicit confirmation, like every destructive action
        resp = client.delete(f"/api/clientes/{cliente_id}", params={"confirmar": "true"})
        assert resp.status_code == 200 and resp.json()["deleted"] is True
        assert client.get(f"/api/clientes/{cliente_id}").status_code == 404

    session = SyncSessionLocal()
    try:
        assert session.get(Cliente, cliente_id) is None
        aviso = session.get(Sancionado, aviso_id)
        assert aviso is not None and aviso.cliente_id is None and aviso.estado_oportunidad == "revisada"
        assert session.get(Notificacion, alerta_id).cliente_id is None
        assert session.execute(select(NotaCliente)).scalars().all() == []
        assert session.execute(select(AccionAgendada)).scalars().all() == []
        vinculo = session.execute(select(VinculoCliente).where(VinculoCliente.cliente_id == otro_id)).scalars().one()
        assert vinculo.cliente_vinculado_id is None and vinculo.nombre == nombre
    finally:
        session.close()


@pytest.mark.integration
def test_a_client_with_invoices_cannot_be_deleted(monkeypatch, tmp_path, clean_database):
    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    cliente = _cliente(session)
    session.commit()
    generar_factura(session, cliente, cuantia=100, concepto="Servicio")
    cliente_id = cliente.id
    session.close()
    with TestClient(app) as client:
        resp = client.delete(f"/api/clientes/{cliente_id}", params={"confirmar": "true"})
        assert resp.status_code == 409 and "factura" in resp.json()["detail"]
        assert client.get(f"/api/clientes/{cliente_id}").status_code == 200       # nothing was removed


@pytest.mark.integration
def test_deleting_a_client_removes_its_contract_pdfs(monkeypatch, tmp_path, clean_database):
    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    cliente = _cliente(session)
    session.commit()
    documento = generar_contrato(session, cliente, precio=130, servicio="Alerta BOE Tráfico", forma_pago="Transferencia")
    ruta = documento.pdf_path
    cliente_id = cliente.id
    session.close()
    assert os.path.exists(ruta)
    with TestClient(app) as client:
        assert client.delete(f"/api/clientes/{cliente_id}", params={"confirmar": "true"}).status_code == 200
    assert not os.path.exists(ruta)


# --- information-only clients ------------------------------------------------

@pytest.mark.integration
def test_information_only_clients_are_a_separate_state_and_filter(clean_database):
    session = SyncSessionLocal()
    real = _cliente(session, estado_cliente="activo")
    solo_info = _cliente(session, estado_cliente="activo")
    session.commit()
    real_id, info_id = real.id, solo_info.id
    session.close()
    with TestClient(app) as client:
        assert client.patch(f"/api/clientes/{info_id}", json={"estado_cliente": "informado"}).status_code == 200
        assert client.patch(f"/api/clientes/{info_id}", json={"estado_cliente": "pendiente"}).status_code == 422
        ids = lambda estado: {c["id"] for c in client.get("/api/clientes", params={"estado_cliente": estado}).json()["items"]}  # noqa: E731
        assert ids("informado") == {info_id} and ids("activo") == {real_id}
        titulos = [a["titulo"] for a in client.get(f"/api/clientes/{info_id}").json()["actividades"]]
        assert any("activo → informado" in t for t in titulos)


@pytest.mark.integration
def test_generating_a_contract_promotes_an_information_only_prospect(monkeypatch, tmp_path, clean_database):
    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    cliente = _cliente(session, estado_cliente="informado")
    session.commit()
    generar_contrato(session, cliente, precio=130, servicio="Alerta BOE Tráfico", forma_pago="Transferencia", fecha_inicio=date(2026, 10, 5))
    session.refresh(cliente)
    assert cliente.estado_cliente == "activo"
    assert cliente.fecha_contrato == date(2026, 10, 5) and float(cliente.precio_contrato) == 130.0
    session.close()


@pytest.mark.integration
def test_the_radar_watches_information_only_clients_too(clean_database):
    from app.services.alertas import ejecutar_radar_clientes

    session = SyncSessionLocal()
    _cliente(session, estado_cliente="informado")
    _cliente(session, estado_cliente="inactivo")
    session.commit()
    assert ejecutar_radar_clientes(session)["clientes_revisados"] == 1
    session.close()


# --- agenda --------------------------------------------------------------------

@pytest.mark.integration
def test_scheduling_any_kind_of_action_works_with_a_date(clean_database):
    """"Agendar" in the client's ficha: a task used to violate the activity
    log's CHECK constraint and answer 500; there was no way to give a date."""
    session = SyncSessionLocal()
    cliente = _cliente(session)
    session.commit()
    cliente_id = cliente.id
    session.close()
    manana = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    with TestClient(app) as client:
        for horas, tipo in enumerate(("tarea", "email", "llamada")):
            cuando = manana + timedelta(hours=horas)
            resp = client.post(f"/api/clientes/{cliente_id}/acciones", json={
                "tipo": tipo, "titulo": f"Pendiente {tipo}", "fecha_programada": cuando.isoformat(), "notas": "recordar contrato",
            })
            assert resp.status_code == 200, (tipo, resp.text)
            assert resp.json()["fecha_programada"].startswith(cuando.strftime("%Y-%m-%dT%H:%M"))
        detalle = client.get(f"/api/clientes/{cliente_id}").json()
        # soonest due first
        assert [a["tipo"] for a in detalle["acciones"]] == ["tarea", "email", "llamada"]


@pytest.mark.integration
def test_agenda_orders_by_date_flags_overdue_and_can_be_edited(clean_database):
    session = SyncSessionLocal()
    cliente = _cliente(session, nombre_razon_social="Acme SL")
    ahora = datetime.now(timezone.utc)
    ayer = AccionAgendada(cliente_id=cliente.id, tipo="llamada", titulo="Vencida", fecha_programada=ahora - timedelta(days=1))
    futura = AccionAgendada(cliente_id=cliente.id, tipo="email", titulo="Futura", fecha_programada=ahora + timedelta(days=3))
    sin_fecha = AccionAgendada(cliente_id=cliente.id, tipo="tarea", titulo="Sin fecha")
    hecha = AccionAgendada(cliente_id=cliente.id, tipo="llamada", titulo="Hecha", estado="hecha", fecha_programada=ahora)
    session.add_all([futura, sin_fecha, ayer, hecha])
    session.commit()
    cliente_id, ayer_id = cliente.id, ayer.id
    session.close()

    with TestClient(app) as client:
        pendientes = client.get("/api/agenda").json()
        assert [a["titulo"] for a in pendientes] == ["Vencida", "Futura", "Sin fecha"]
        assert pendientes[0]["vencida"] is True and pendientes[1]["vencida"] is False
        assert pendientes[0]["cliente_nombre"] == "Acme SL"
        assert [a["titulo"] for a in client.get("/api/agenda", params={"estado": "todas"}).json()][-1] != ""
        assert [a["titulo"] for a in client.get("/api/agenda", params={"estado": "hecha"}).json()] == ["Hecha"]
        resumen = client.get("/api/agenda/resumen").json()
        assert resumen["vencidas"] == 1 and resumen["sin_fecha"] == 1 and resumen["proximas"] == 1

        nueva_fecha = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0)
        resp = client.patch(f"/api/clientes/{cliente_id}/acciones/{ayer_id}", json={
            "fecha_programada": nueva_fecha.isoformat(), "titulo": "Reprogramada", "notas": "no contestó",
        })
        assert resp.status_code == 200 and resp.json()["titulo"] == "Reprogramada"
        assert [a["titulo"] for a in client.get("/api/agenda").json()][-2:] == ["Reprogramada", "Sin fecha"]
        assert client.patch(f"/api/clientes/{cliente_id}/acciones/{ayer_id}", json={"titulo": "  "}).status_code == 422


# --- invoices ----------------------------------------------------------------

def _configurar_emisor(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "emisor_nombre", "Despacho Judit SL")
    monkeypatch.setattr(settings, "emisor_cif", "B99999999")
    monkeypatch.setattr(settings, "emisor_direccion", "Gran Vía 1, Madrid")
    monkeypatch.setattr(settings, "emisor_iban", "ES9121000418450200051332")
    monkeypatch.setattr(settings, "emisor_iva_porcentaje", 21.0)
    monkeypatch.setattr(settings, "factura_serie", "FAC")
    monkeypatch.setattr(settings, "documentos_dir", str(tmp_path / "docs"))


@pytest.mark.parametrize("serie", ["FAC", "2026/0072#", "A B\\C:D*E?", "ñandú"])
@pytest.mark.integration
def test_an_invoice_with_any_series_can_be_generated_and_downloaded(serie, monkeypatch, tmp_path, clean_database):
    """The series ``2026/0072#`` (a real, sensible one) put a ``/`` in the file
    path: the PDF could not be written and, with a stored path, never downloaded."""
    _configurar_emisor(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "factura_serie", serie)
    session = SyncSessionLocal()
    cliente = _cliente(session)
    session.commit()
    factura = generar_factura(session, cliente, cuantia=100, concepto="Alerta BOE Tráfico")
    factura_id, numero = factura.id, factura.numero
    session.close()
    assert numero.startswith(serie)           # the number shown on the invoice is untouched
    with TestClient(app) as client:
        resp = client.get(f"/api/documentos-comerciales/{factura_id}/pdf")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/pdf" and resp.content.startswith(b"%PDF")
        disposicion = resp.headers["content-disposition"]
        assert ".pdf" in disposicion and "/" not in disposicion.split("filename=")[-1].strip('"')


def test_safe_file_names():
    assert nombre_fichero_seguro("2026/0072#-2026-0001") == "2026-0072-2026-0001"
    assert nombre_fichero_seguro("../../etc/passwd") == "etc-passwd"
    assert nombre_fichero_seguro("") == "documento" and nombre_fichero_seguro(42) == "42"


@pytest.mark.integration
def test_the_new_contract_text_is_the_active_template(monkeypatch, tmp_path, clean_database):
    from app.services.parser import pdf_to_text

    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    cliente = _cliente(session, nombre_razon_social="Cliente Contrato SL", cif_nif="B12345674", telefono="611222333", email="c@c.test")
    session.commit()
    documento = generar_contrato(
        session, cliente, precio=235, servicio="Gestión Tráfico BOE", forma_pago="Transferencia bancaria",
        fecha_inicio=date(2026, 10, 5),
    )
    with open(documento.pdf_path, "rb") as fh:
        texto = pdf_to_text(fh.read())
    session.close()
    assert "B93993376" in texto and "Calle Monlau 35, 08027 de Barcelona" in texto      # the issuer's registered office
    for fragmento in ("ALERTA BOE TRÁFICO", "GESTIÓN TRÁFICO BOE", "ALERTA 360", "GESTIÓN FLOTAS", "GESTIÓN SEDES 360",
                      "REVISIÓN DE EXPEDIENTES ANTERIOR AL CONTRATO", "10 % del importe total"):
        assert fragmento in texto
    assert "Cliente Contrato SL" in texto and "B12345674" in texto and "235,00" in texto and "05/10/2026" in texto
    assert "04/10/2027" in texto or "05/10/2027" in texto
