"""API-level tests for the enrichment cost gates and history endpoint.

Deliberately does NOT exercise the success path of POST /enriquecer or
POST /enriquecimiento/lote: those call Celery's ``.delay()``, which needs a
real broker this test compose does not provision (mirroring how session 1
never exercised /api/scraping/trigger's success path via TestClient either).
Every scenario tested here is rejected by a config check *before* ``.delay()``
is ever reached, so no broker is needed.
"""

from __future__ import annotations

from datetime import date
import os

import pytest

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SyncSessionLocal
from app.main import app
from app.models.documento import BoeDocumento
from app.models.enriquecimiento import EnriquecimientoIntento
from app.models.sancionado import Sancionado

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _opportunity(session, suffix: str) -> Sancionado:
    document = BoeDocumento(boe_id=f"BOE-ENRICH-API-{suffix}", fecha_publicacion=date(2026, 8, 1), titulo="Doc")
    session.add(document)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=document.id, codigo=f"OP-2026-{suffix.zfill(6)}", origen_clave=(f"api-{suffix}" * 10)[:64],
        nombre="Acme Logistica SL",
    )
    session.add(sancionado)
    session.flush()
    return sancionado


@pytest.mark.integration
def test_enrich_endpoint_rejects_when_disabled(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "enrichment_enabled", False)
    session = SyncSessionLocal()
    sancionado = _opportunity(session, "1")
    session.commit()
    sancionado_id = sancionado.id
    session.close()

    with TestClient(app) as client:
        response = client.post(f"/api/sanciones/{sancionado_id}/enriquecer")
        assert response.status_code == 409
        assert "ENRICHMENT_ENABLED" in response.json()["detail"]


@pytest.mark.integration
def test_enrich_endpoint_404_for_missing_sancionado(clean_database):
    with TestClient(app) as client:
        response = client.post("/api/sanciones/999999/enriquecer")
        assert response.status_code == 404


@pytest.mark.integration
def test_batch_endpoint_requires_confirmation(clean_database):
    with TestClient(app) as client:
        response = client.post("/api/enriquecimiento/lote", json={"confirmar": False})
        assert response.status_code == 422


@pytest.mark.integration
def test_batch_endpoint_requires_batch_enabled_flag(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "enrichment_batch_enabled", False)
    with TestClient(app) as client:
        response = client.post("/api/enriquecimiento/lote", json={"confirmar": True})
        assert response.status_code == 409
        assert "ENRICHMENT_BATCH_ENABLED" in response.json()["detail"]


@pytest.mark.integration
def test_batch_endpoint_requires_configured_provider(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "enrichment_batch_enabled", True)
    monkeypatch.setattr(settings, "enrichment_enabled", False)
    with TestClient(app) as client:
        response = client.post("/api/enriquecimiento/lote", json={"confirmar": True})
        assert response.status_code == 409
        assert "ENRICHMENT_ENABLED" in response.json()["detail"]


@pytest.mark.integration
def test_enrichment_history_endpoint_lists_attempts(clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session, "2")
    session.commit()
    session.add(EnriquecimientoIntento(
        sancionado_id=sancionado.id, proveedor="fixture", resultado="no_encontrado", consulta="Acme Logistica SL",
    ))
    session.commit()
    sancionado_id = sancionado.id
    session.close()

    with TestClient(app) as client:
        response = client.get(f"/api/sanciones/{sancionado_id}/enriquecimiento")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["resultado"] == "no_encontrado"
        assert body[0]["proveedor"] == "fixture"
