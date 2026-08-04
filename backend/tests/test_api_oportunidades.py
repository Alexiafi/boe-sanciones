from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os

import pytest

from fastapi.testclient import TestClient

from app.database import SyncSessionLocal
from app.main import app
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.models.scraping_run import ScrapingRun

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _opportunity(session, suffix: str, published: date, *, state: str = "nueva", materia: str = "Tráfico", person: str = "fisica", amount: float = 100, contact: str | None = None):
    document = BoeDocumento(boe_id=f"BOE-TEST-{suffix}", fecha_publicacion=published, titulo=f"Documento {suffix}")
    session.add(document)
    session.flush()
    item = Sancionado(
        boe_document_id=document.id, codigo=f"OP-{published.year}-{int(suffix):06d}", origen_clave=(suffix * 64)[:64],
        estado_oportunidad=state, nombre=f"Persona {suffix}", tipo_persona=person, dominio_material=materia,
        importe_multa_eur=amount, telefono=contact,
    )
    session.add(item)
    return item


@pytest.mark.integration
def test_filters_default_range_and_safe_patch(clean_database):
    session = SyncSessionLocal()
    today = date.today()
    _opportunity(session, "1", today, state="nueva", materia="Tráfico", contact="600123123")
    recent = _opportunity(session, "2", today - timedelta(days=2), state="contactada", materia="Sanidad", person="juridica", amount=500)
    _opportunity(session, "3", today - timedelta(days=31), state="descartada")
    session.commit()
    with TestClient(app) as client:
        response = client.get("/api/sanciones")
        assert response.status_code == 200
        assert response.json()["total"] == 2
        filtered = client.get("/api/sanciones", params={"estado_oportunidad": "contactada", "tipo_persona": "juridica", "materia": "sanidad", "cuantia_min": 400, "solo_con_contacto": "false"})
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()["items"]] == [recent.id]
        patched = client.patch(f"/api/sanciones/{recent.id}", json={"estado_oportunidad": "revisada", "telefono": " +34 911 000 000 ", "email": "contacto@example.test"})
        assert patched.status_code == 200
        assert patched.json()["estado_oportunidad"] == "revisada"
        forbidden = client.patch(f"/api/sanciones/{recent.id}", json={"estado_oportunidad": "cliente"})
        assert forbidden.status_code == 422
        forbidden_field = client.patch(f"/api/sanciones/{recent.id}", json={"nombre": "No permitido"})
        assert forbidden_field.status_code == 422
        # Regression: an explicit null used to slip past validation and crash the
        # NOT NULL column with a 500 IntegrityError. It must be a 422 instead.
        null_estado = client.patch(f"/api/sanciones/{recent.id}", json={"estado_oportunidad": None})
        assert null_estado.status_code == 422
        # null remains valid for telefono/email: it is how contact gets cleared.
        cleared = client.patch(f"/api/sanciones/{recent.id}", json={"telefono": None})
        assert cleared.status_code == 200
        assert cleared.json()["telefono"] is None
    session.close()


@pytest.mark.integration
def test_contacto_estado_filter(clean_database):
    session = SyncSessionLocal()
    today = date.today()
    encontrado = _opportunity(session, "6", today, contact="600123123")
    encontrado.contacto_estado = "encontrado"
    pendiente = _opportunity(session, "7", today)
    session.commit()
    with TestClient(app) as client:
        found = client.get("/api/sanciones", params={"contacto_estado": "encontrado"})
        assert found.status_code == 200
        assert [item["id"] for item in found.json()["items"]] == [encontrado.id]

        pending = client.get("/api/sanciones", params={"contacto_estado": "pendiente"})
        assert [item["id"] for item in pending.json()["items"]] == [pendiente.id]

        invalid = client.get("/api/sanciones", params={"contacto_estado": "bogus"})
        assert invalid.status_code == 422
    session.close()


@pytest.mark.integration
def test_manual_contact_patch_marks_and_releases_manual_state(clean_database):
    session = SyncSessionLocal()
    today = date.today()
    item = _opportunity(session, "5", today)
    session.commit()
    item_id = item.id
    session.close()

    with TestClient(app) as client:
        detail = client.get(f"/api/sanciones/{item_id}").json()
        assert detail["contacto_estado"] == "pendiente"

        patched = client.patch(f"/api/sanciones/{item_id}", json={"telefono": "611222333"})
        assert patched.status_code == 200
        body = patched.json()
        assert body["contacto_estado"] == "manual"
        assert body["contacto_fuente"] == "manual"
        assert body["contacto_confidence"] == 1.0

        # Editing a field unrelated to contact must not touch contacto_estado.
        untouched = client.patch(f"/api/sanciones/{item_id}", json={"estado_oportunidad": "revisada"})
        assert untouched.json()["contacto_estado"] == "manual"

        # Clearing every contact field releases the manual lock so automatic
        # enrichment is eligible to run again.
        cleared = client.patch(f"/api/sanciones/{item_id}", json={"telefono": None})
        assert cleared.json()["contacto_estado"] == "pendiente"
        assert cleared.json()["contacto_fuente"] is None


@pytest.mark.integration
def test_gaps_endpoint_is_read_only_and_bounded(clean_database):
    session = SyncSessionLocal()
    today = date.today()
    yesterday = today - timedelta(days=1)
    session.add(ScrapingRun(fecha_boe=today, status="completed", started_at=datetime.now(timezone.utc)))
    # A failed run must not count as "covered": the gap for yesterday stays open.
    session.add(ScrapingRun(fecha_boe=yesterday, status="failed", started_at=datetime.now(timezone.utc)))
    session.commit()
    with TestClient(app) as client:
        response = client.get("/api/scraping/gaps", params={"days": 3})
        assert response.status_code == 200
        body = response.json()
        assert today.isoformat() not in body["gaps"]
        assert yesterday.isoformat() in body["gaps"]

        too_many = client.get("/api/scraping/gaps", params={"days": 999})
        assert too_many.status_code == 422
    session.close()
