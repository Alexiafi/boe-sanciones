from __future__ import annotations

from datetime import date, timedelta
import os

import pytest

from fastapi.testclient import TestClient

from app.database import SyncSessionLocal
from app.main import app
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado

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
    session.close()
