"""Clientes/CRM core: conversion idempotency, code allocation, and the CRUD
surface (notas, actividad, acciones). All against the ephemeral PostgreSQL,
no mocks needed since none of this touches the network or OpenAI.
"""

from __future__ import annotations

import asyncio
from datetime import date
import os

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SyncSessionLocal, async_session_factory
from app.main import app
from app.models.cliente import ActividadCliente, Cliente
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.services.clientes import allocate_codigo_cliente

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _opportunity(session, *, suffix: str, nombre="Acme Logistica SL", identificador="B12345678",
                  amount: float = 250, tipo_persona="juridica") -> Sancionado:
    document = BoeDocumento(boe_id=f"BOE-CLI-{suffix}", fecha_publicacion=date(2026, 8, 1), titulo=f"Doc {suffix}")
    session.add(document)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=document.id, codigo=f"OP-2026-{suffix.zfill(6)}", origen_clave=(f"cli-{suffix}" * 10)[:64],
        nombre=nombre, identificador=identificador, tipo_persona=tipo_persona,
        tipo_identificador="CIF" if tipo_persona == "juridica" else "DNI",
        importe_multa_eur=amount, telefono="600111222", email="contacto@acme.test",
    )
    session.add(sancionado)
    session.flush()
    return sancionado


@pytest.mark.integration
def test_conversion_is_idempotent_and_records_activity(clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session, suffix="1")
    session.commit()
    sancionado_id = sancionado.id
    session.close()

    with TestClient(app) as client:
        first = client.post(f"/api/sanciones/{sancionado_id}/convertir")
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["created"] is True
        assert first_body["cliente"]["codigo"].startswith("CLI-")
        cliente_id = first_body["cliente"]["id"]

        second = client.post(f"/api/sanciones/{sancionado_id}/convertir")
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["created"] is False
        assert second_body["cliente"]["id"] == cliente_id

        detail = client.get(f"/api/sanciones/{sancionado_id}")
        assert detail.status_code == 200
        assert detail.json()["estado_oportunidad"] == "cliente"

    session = SyncSessionLocal()
    clientes = session.execute(select(Cliente)).scalars().all()
    assert len(clientes) == 1  # the second call must not have created a duplicate
    actividades = session.execute(
        select(ActividadCliente).where(ActividadCliente.cliente_id == cliente_id, ActividadCliente.tipo == "conversion")
    ).scalars().all()
    assert len(actividades) == 1
    session.close()


@pytest.mark.integration
def test_conversion_recovers_when_cliente_id_was_not_synced(clean_database):
    """Covers find_existing_cliente's second lookup path: a Cliente already
    references this Sancionado via sancion_origen_id, but sancionado.cliente_id
    was never written back (e.g. a prior request committed the Cliente and
    crashed before that second update). Conversion must still be idempotent."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session, suffix="2")
    session.commit()
    cliente = Cliente(
        codigo="CLI-2026-0001", nombre_razon_social=sancionado.nombre, sancion_origen_id=sancionado.id,
    )
    session.add(cliente)
    session.commit()
    sancionado_id, cliente_id = sancionado.id, cliente.id
    session.close()

    with TestClient(app) as client:
        response = client.post(f"/api/sanciones/{sancionado_id}/convertir")
        assert response.status_code == 200
        body = response.json()
        assert body["created"] is False
        assert body["cliente"]["id"] == cliente_id

    session = SyncSessionLocal()
    assert session.execute(select(Cliente)).scalars().all().__len__() == 1
    refreshed = session.get(Sancionado, sancionado_id)
    assert refreshed.cliente_id == cliente_id
    assert refreshed.estado_oportunidad == "cliente"
    session.close()


@pytest.mark.integration
def test_conversion_returns_404_for_missing_opportunity(clean_database):
    with TestClient(app) as client:
        response = client.post("/api/sanciones/999999/convertir")
        assert response.status_code == 404


@pytest.mark.integration
def test_client_code_allocation_is_concurrent_safe(clean_database):
    async def allocate() -> str:
        async with async_session_factory() as session:
            code = await allocate_codigo_cliente(session, 2028)
            await session.commit()
            return code

    async def run_both() -> list[str]:
        return await asyncio.gather(allocate(), allocate())

    codes = asyncio.run(run_both())
    assert set(codes) == {"CLI-2028-0001", "CLI-2028-0002"}


@pytest.mark.integration
def test_deuda_pendiente_sums_all_linked_sanciones(clean_database):
    session = SyncSessionLocal()
    primero = _opportunity(session, suffix="10", amount=100)
    segundo = _opportunity(session, suffix="11", amount=250, nombre="Acme Logistica SL", identificador="B12345678")
    session.commit()
    primero_id, segundo_id = primero.id, segundo.id
    session.close()

    with TestClient(app) as client:
        converted = client.post(f"/api/sanciones/{primero_id}/convertir").json()
        cliente_id = converted["cliente"]["id"]
        assert converted["cliente"]["deuda_pendiente_eur"] == 100

        # Link the second opportunity to the same client directly (simulating
        # a second sanction against an already-converted client) and confirm
        # the ficha's deuda is the live sum, not a stale stored value.
        session = SyncSessionLocal()
        segundo_row = session.get(Sancionado, segundo_id)
        segundo_row.cliente_id = cliente_id
        session.commit()
        session.close()

        detail = client.get(f"/api/clientes/{cliente_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["deuda_pendiente_eur"] == 350
        assert {item["id"] for item in body["sanciones"]} == {primero_id, segundo_id}


@pytest.mark.integration
def test_clientes_directory_filters_and_notas_actividad_acciones(clean_database):
    session = SyncSessionLocal()
    activo = _opportunity(session, suffix="20", nombre="Transportes del Sur SL")
    inactivo = _opportunity(session, suffix="21", nombre="Otra Empresa SL", identificador="B99999999")
    session.commit()
    activo_id, inactivo_id = activo.id, inactivo.id
    session.close()

    with TestClient(app) as client:
        cliente_activo = client.post(f"/api/sanciones/{activo_id}/convertir").json()["cliente"]
        cliente_inactivo = client.post(f"/api/sanciones/{inactivo_id}/convertir").json()["cliente"]
        client.patch(f"/api/clientes/{cliente_inactivo['id']}", json={"estado_cliente": "inactivo", "sector": "Logística"})

        listado = client.get("/api/sanciones".replace("sanciones", "clientes"), params={"estado_cliente": "inactivo"})
        assert listado.status_code == 200
        ids = {item["id"] for item in listado.json()["items"]}
        assert ids == {cliente_inactivo["id"]}

        search = client.get("/api/clientes", params={"search": "Transportes"})
        assert {item["id"] for item in search.json()["items"]} == {cliente_activo["id"]}

        # PATCH must reject an explicit null the same way session 1 does for estado_oportunidad.
        null_patch = client.patch(f"/api/clientes/{cliente_activo['id']}", json={"estado_cliente": None})
        assert null_patch.status_code == 422
        forbidden_field = client.patch(f"/api/clientes/{cliente_activo['id']}", json={"codigo": "CLI-2026-9999"})
        assert forbidden_field.status_code == 422

        nota = client.post(f"/api/clientes/{cliente_activo['id']}/notas", json={"texto": "Primera llamada realizada"})
        assert nota.status_code == 200
        blank_nota = client.post(f"/api/clientes/{cliente_activo['id']}/notas", json={"texto": "   "})
        assert blank_nota.status_code == 422

        accion = client.post(
            f"/api/clientes/{cliente_activo['id']}/acciones",
            json={"tipo": "llamada", "titulo": "Llamar para cerrar contrato"},
        )
        assert accion.status_code == 200
        accion_id = accion.json()["id"]
        marcada = client.patch(f"/api/clientes/{cliente_activo['id']}/acciones/{accion_id}", json={"estado": "hecha"})
        assert marcada.status_code == 200
        assert marcada.json()["estado"] == "hecha"

        actividad = client.get(f"/api/clientes/{cliente_activo['id']}/actividad")
        tipos = {item["tipo"] for item in actividad.json()}
        # conversion (from convertir) + nota (from add_nota) + llamada (from add_accion)
        assert {"conversion", "nota", "llamada"}.issubset(tipos)

        detail = client.get(f"/api/clientes/{cliente_activo['id']}")
        assert detail.status_code == 200
        assert len(detail.json()["notas"]) == 1
        assert len(detail.json()["acciones"]) == 1
