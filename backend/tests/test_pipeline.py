from __future__ import annotations

from datetime import date
import os

import pytest

from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.services.extractor import AfectadoExtraido, ResultadoExtraccion
from app.tasks import scraping

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


@pytest.mark.integration
def test_pipeline_fixture_is_cost_free_then_idempotent(monkeypatch, clean_database):
    document = {
        "identificador": "BOE-2026-TEST-1", "fecha_publicacion": date(2026, 8, 1), "titulo": "Documento de prueba", "seccion_codigo": "3",
    }
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    calls = []

    def fake_extractor(text, title):
        calls.append((text, title))
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador="A-1", localidad="Sevilla", importe_deuda_eur=80)])

    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto de fixture", "xml"),
        extractor=fake_extractor, send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    first = scraping.run_scraping("2026-08-01", dependencies=deps)
    assert first["extracted"] == 0 and calls == []

    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    second = scraping.run_scraping("2026-08-01", force=True, permitir_extraccion_pago=True, dependencies=deps)
    assert second["extracted"] == 1 and len(calls) == 1
    third = scraping.run_scraping("2026-08-01", permitir_extraccion_pago=True, dependencies=deps)
    assert third["extracted"] == 0

    session = SyncSessionLocal()
    try:
        stored = session.execute(select(Sancionado)).scalars().all()
        source = session.execute(select(BoeDocumento)).scalar_one()
        assert len(stored) == 1 and stored[0].codigo == "OP-2026-000001"
        assert source.extraction_status == "completed"
    finally:
        session.close()
