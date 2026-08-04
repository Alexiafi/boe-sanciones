"""Vínculos (administrador/conductor/filial) CRUD, automatic sanction
assignment to existing clients, and vínculo-aware historical search."""

from __future__ import annotations

from datetime import date
import os

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SyncSessionLocal
from app.main import app
from app.models.cliente import ActividadCliente, Cliente, VinculoCliente
from app.models.documento import BoeDocumento
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.services.historico.busqueda import buscar_historico
from app.services.historico.indexado import upsert_historico_doc
from app.services.historico.patterns import extraer_claves
from app.services.oportunidades import allocate_codigo
from app.services.vinculos import asignar_sancion_a_cliente, indice_identificadores

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _cliente(session, *, suffix: str, cif_nif: str | None = None, nombre: str = "Acme Logistica SL") -> Cliente:
    doc = BoeDocumento(boe_id=f"BOE-VIN-{suffix}", fecha_publicacion=date(2026, 7, 1), titulo="Origen")
    session.add(doc)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
        origen_clave=f"clave-vin-{suffix}", nombre=nombre,
    )
    session.add(sancionado)
    session.flush()
    cliente = Cliente(
        codigo=f"CLI-2026-{suffix}", nombre_razon_social=nombre, cif_nif=cif_nif, sancion_origen_id=sancionado.id,
    )
    session.add(cliente)
    session.flush()
    return cliente


def _sancion_suelta(session, *, suffix: str, identificador: str, nombre: str = "Nueva Sancion") -> Sancionado:
    doc = BoeDocumento(boe_id=f"BOE-VIN-SUELTA-{suffix}", fecha_publicacion=date(2026, 8, 1), titulo="Nueva")
    session.add(doc)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="nueva",
        origen_clave=f"clave-suelta-{suffix}", nombre=nombre, identificador=identificador,
    )
    session.add(sancionado)
    session.flush()
    return sancionado


@pytest.mark.integration
def test_asignacion_automatica_por_identificador_de_cliente(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, suffix="1", cif_nif="B12345678")
        sancion = _sancion_suelta(session, suffix="1", identificador="B12345678")
        session.commit()
        cliente_id, sancion_id = cliente.id, sancion.id

        indice = indice_identificadores(session)
        assert indice["B12345678"] == (cliente_id, None)

        creada = asignar_sancion_a_cliente(session, sancion, cliente_id, None)
        session.commit()
        assert creada is True

        refrescada = session.get(Sancionado, sancion_id)
        assert refrescada.cliente_id == cliente_id
        assert refrescada.vinculo_id is None
        assert refrescada.estado_oportunidad == "cliente"

        notifs = session.execute(
            select(Notificacion).where(Notificacion.cliente_id == cliente_id)
        ).scalars().all()
        assert len(notifs) == 1
        assert "cliente" in notifs[0].titulo.lower()

        actividades = session.execute(
            select(ActividadCliente).where(ActividadCliente.cliente_id == cliente_id, ActividadCliente.tipo == "sistema")
        ).scalars().all()
        assert len(actividades) == 1

        # Idempotent: a second call on the already-linked sancionado is a no-op.
        segunda = asignar_sancion_a_cliente(session, refrescada, cliente_id, None)
        session.commit()
        assert segunda is False
        assert session.execute(
            select(Notificacion).where(Notificacion.cliente_id == cliente_id)
        ).scalars().all().__len__() == 1
    finally:
        session.close()


@pytest.mark.integration
def test_asignacion_automatica_por_identificador_de_vinculo(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, suffix="2", cif_nif="B87654321")
        vinculo = VinculoCliente(
            cliente_id=cliente.id, rol="administrador", nombre="Alberto Garcia",
            tipo_persona="fisica", identificador="12345678Z", tipo_identificador="DNI",
        )
        session.add(vinculo)
        session.flush()
        sancion = _sancion_suelta(session, suffix="2", identificador="12345678Z")
        session.commit()
        cliente_id, vinculo_id, sancion_id = cliente.id, vinculo.id, sancion.id

        indice = indice_identificadores(session)
        assert indice["12345678Z"] == (cliente_id, vinculo_id)

        asignar_sancion_a_cliente(session, sancion, cliente_id, vinculo_id)
        session.commit()

        refrescada = session.get(Sancionado, sancion_id)
        assert refrescada.cliente_id == cliente_id
        assert refrescada.vinculo_id == vinculo_id

        notif = session.execute(
            select(Notificacion).where(Notificacion.cliente_id == cliente_id)
        ).scalar_one()
        assert "Alberto Garcia" in notif.titulo
        assert "administrador" in notif.titulo
    finally:
        session.close()


@pytest.mark.integration
def test_asignacion_no_mueve_sancion_ya_vinculada_a_otro_cliente(clean_database):
    session = SyncSessionLocal()
    try:
        cliente_a = _cliente(session, suffix="3a", cif_nif="B11111111")
        cliente_b = _cliente(session, suffix="3b", cif_nif="B22222222")
        sancion = _sancion_suelta(session, suffix="3", identificador="B22222222")
        sancion.cliente_id = cliente_a.id
        session.commit()

        creada = asignar_sancion_a_cliente(session, sancion, cliente_b.id, None)
        session.commit()

        assert creada is False
        assert session.get(Sancionado, sancion.id).cliente_id == cliente_a.id
    finally:
        session.close()


@pytest.mark.integration
def test_buscar_historico_incluye_matches_de_vinculos(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, suffix="4", cif_nif="B99999999", nombre="Transportes del Sur SL")
        vinculo = VinculoCliente(
            cliente_id=cliente.id, rol="administrador", nombre="Alberto Garcia",
            tipo_persona="fisica", identificador="11111111H", tipo_identificador="DNI",
        )
        session.add(vinculo)
        session.flush()

        texto = "Sancionado ALBERTO GARCIA con DNI 11111111H por infraccion de trafico."
        claves = extraer_claves(texto, "Sancion administrador")
        upsert_historico_doc(
            session, boe_id="BOE-VIN-HIST-1", fuente="boe", fecha_publicacion=date(2026, 1, 1),
            titulo="Sancion administrador", origen_indexado="backfill", texto=texto, claves=claves,
        )
        session.commit()
        vinculo_id = vinculo.id

        resultado = buscar_historico(session, cliente)
        assert len(resultado["resultados"]) == 1
        encontrado = resultado["resultados"][0]
        assert encontrado.vinculo_id == vinculo_id
        assert encontrado.via_match == "dni"
        assert len(resultado["nuevos"]) == 1

        # Re-running must not create a second alert-worthy "nuevo" entry.
        segunda = buscar_historico(session, cliente)
        assert len(segunda["resultados"]) == 1
        assert segunda["nuevos"] == []
    finally:
        session.close()


def _api_cliente(client: TestClient, *, sufijo: str) -> dict:
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, suffix=f"api-{sufijo}", cif_nif=f"B0000{sufijo}")
        session.commit()
        return {"id": cliente.id}
    finally:
        session.close()


@pytest.mark.integration
def test_vinculos_crud_endpoint(clean_database):
    with TestClient(app) as client:
        cliente = _api_cliente(client, sufijo="1")
        cliente_id = cliente["id"]

        sin_datos = client.post(f"/api/clientes/{cliente_id}/vinculos", json={"rol": "administrador"})
        assert sin_datos.status_code == 422  # neither nombre nor cliente_vinculado_id

        creado = client.post(
            f"/api/clientes/{cliente_id}/vinculos",
            json={"rol": "administrador", "nombre": "Alberto Garcia", "identificador": "22222222J"},
        )
        assert creado.status_code == 200
        vinculo_id = creado.json()["id"]

        listado = client.get(f"/api/clientes/{cliente_id}/vinculos")
        assert listado.status_code == 200
        assert len(listado.json()) == 1

        detalle = client.get(f"/api/clientes/{cliente_id}")
        assert len(detalle.json()["vinculos"]) == 1

        actualizado = client.patch(
            f"/api/clientes/{cliente_id}/vinculos/{vinculo_id}", json={"rol": "conductor"}
        )
        assert actualizado.status_code == 200
        assert actualizado.json()["rol"] == "conductor"

        rol_vacio = client.patch(f"/api/clientes/{cliente_id}/vinculos/{vinculo_id}", json={"rol": None})
        assert rol_vacio.status_code == 422

        otro_cliente = _api_cliente(client, sufijo="2")
        patch_ajeno = client.patch(
            f"/api/clientes/{otro_cliente['id']}/vinculos/{vinculo_id}", json={"rol": "empleado"}
        )
        assert patch_ajeno.status_code == 404

        borrado = client.delete(f"/api/clientes/{cliente_id}/vinculos/{vinculo_id}")
        assert borrado.status_code == 200
        assert client.get(f"/api/clientes/{cliente_id}/vinculos").json() == []
