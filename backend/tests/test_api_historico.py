"""API-level tests for the historical index endpoints.

Like test_api_enriquecimiento.py, this deliberately never exercises a path
that reaches Celery's ``.delay()`` (no broker in this test compose) — only
scenarios rejected by a gate/validation check before that point.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SyncSessionLocal
from app.main import app
from app.models.historico import HistoricoDoc
from app.tasks.historico_backfill import token_confirmacion

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


@pytest.mark.integration
def test_plan_no_toca_la_red_ni_escribe(clean_database):
    with TestClient(app) as client:
        resp = client.post(
            "/api/historico/backfill/plan",
            json={"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-03"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dias"] == 3
    assert "token" in body


@pytest.mark.integration
def test_backfill_requiere_confirmar(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "historico_backfill_enabled", True)
    with TestClient(app) as client:
        resp = client.post(
            "/api/historico/backfill",
            json={"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-03", "confirmar": False},
        )
    assert resp.status_code == 422


@pytest.mark.integration
def test_backfill_requiere_flag_habilitado(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "historico_backfill_enabled", False)
    token = token_confirmacion(
        date(2026, 7, 1), date(2026, 7, 3),
        settings.historico_backfill_max_dias_por_lote, settings.historico_backfill_max_docs_por_lote,
    )
    with TestClient(app) as client:
        resp = client.post(
            "/api/historico/backfill",
            json={
                "fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-03",
                "confirmar": True, "confirmacion": token,
            },
        )
    assert resp.status_code == 409
    assert "HISTORICO_BACKFILL_ENABLED" in resp.json()["detail"]


@pytest.mark.integration
def test_backfill_token_invalido_no_llega_a_delay(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "historico_backfill_enabled", True)
    with TestClient(app) as client:
        resp = client.post(
            "/api/historico/backfill",
            json={
                "fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-03",
                "confirmar": True, "confirmacion": "un-token-cualquiera",
            },
        )
    assert resp.status_code == 422


@pytest.mark.integration
def test_consulta_requiere_al_menos_un_criterio(clean_database):
    with TestClient(app) as client:
        resp = client.post("/api/historico/consulta", json={})
    assert resp.status_code == 422


@pytest.mark.integration
def test_consulta_es_solo_lectura(clean_database):
    session = SyncSessionLocal()
    try:
        session.add(HistoricoDoc(
            boe_id="BOE-API-HIST-1", fuente="boe", fecha_publicacion=date(2026, 1, 1), titulo="Doc",
            identificadores=["B12345674"], nombres_norm="ACME LOGISTICA SL",
        ))
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.post("/api/historico/consulta", json={"cif": "B12345674"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["resultados"]) == 1
    assert body["resultados"][0]["via_match"] == "cif"
    assert body["avisos"]
    assert body["cobertura_teu"]["consulta_en_vivo"] is False  # off by default


@pytest.mark.integration
def test_cobertura_refleja_lo_indexado(clean_database):
    session = SyncSessionLocal()
    try:
        session.add(HistoricoDoc(
            boe_id="BOE-API-HIST-2", fuente="boe", fecha_publicacion=date(2026, 2, 1), titulo="Doc",
        ))
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get("/api/historico/cobertura")
    assert resp.status_code == 200
    body = resp.json()
    assert body["boe_dias_indexados"] >= 1


@pytest.mark.integration
def test_list_historico_paginado(clean_database):
    session = SyncSessionLocal()
    try:
        session.add(HistoricoDoc(
            boe_id="BOE-API-HIST-3", fuente="boe", fecha_publicacion=date(2026, 3, 1), titulo="Doc listado",
        ))
        session.commit()
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get("/api/historico", params={"fuente": "boe"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(item["fuente"] == "boe" for item in body["items"])


@pytest.mark.integration
def test_cliente_historico_extraer_requiere_confirmar(clean_database):
    from app.models.cliente import Cliente
    from app.models.documento import BoeDocumento
    from app.models.sancionado import Sancionado
    from app.services.oportunidades import allocate_codigo

    session = SyncSessionLocal()
    try:
        doc = BoeDocumento(boe_id="BOE-API-HIST-CLI", fecha_publicacion=date(2026, 1, 1), titulo="Origen")
        session.add(doc)
        session.flush()
        sancionado = Sancionado(
            boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
            origen_clave="clave-api-hist", nombre="Cliente API",
        )
        session.add(sancionado)
        session.flush()
        cliente = Cliente(codigo="CLI-2026-APIH", nombre_razon_social="Cliente API", sancion_origen_id=sancionado.id)
        session.add(cliente)
        session.commit()
        cliente_id = cliente.id
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.post(f"/api/clientes/{cliente_id}/historico/extraer", json={"resultado_ids": [1], "confirmar": False})
    assert resp.status_code == 422
