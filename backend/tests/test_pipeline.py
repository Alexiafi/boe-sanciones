from __future__ import annotations

from datetime import date
import os

import pytest

from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.scraping_run import ScrapingRun
from app.models.sancionado import Sancionado
from app.services import extractor as extractor_module
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


@pytest.mark.integration
def test_disabled_extraction_never_constructs_openai_client(monkeypatch, clean_database):
    """No code path may build an OpenAI client while extraction is disabled.

    Unlike the fixture-extractor test above, this uses the REAL ``extract_sanctions``
    so a regression that calls OpenAI despite the disabled flag would be caught here,
    not hidden behind a fake extractor.
    """

    def _boom(*args, **kwargs):  # pragma: no cover - only invoked on regression
        raise AssertionError("OpenAI client must not be constructed when extraction is disabled")

    monkeypatch.setattr(extractor_module, "OpenAI", _boom)
    monkeypatch.setattr(settings, "openai_extraction_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", "")

    document = {
        "identificador": "BOE-2026-TEST-DISABLED", "fecha_publicacion": date(2026, 8, 1),
        "titulo": "Documento de prueba", "seccion_codigo": "3",
    }
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto", "xml"),
        send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    # Extraction stays disabled: the pipeline must not even reach the real extractor.
    result = scraping.run_scraping("2026-08-01", dependencies=deps)
    assert result["extracted"] == 0
    document_row = SyncSessionLocal()
    try:
        stored = document_row.execute(select(BoeDocumento)).scalar_one()
        assert stored.extraction_status == "pending"
    finally:
        document_row.close()

    # A manual request for paid extraction without both cost gates open must raise,
    # never silently fall through to a real OpenAI call.
    with pytest.raises(scraping.PaidExtractionNotAllowed):
        scraping.run_scraping("2026-08-01", permitir_extraccion_pago=True, dependencies=deps)


@pytest.mark.integration
def test_extraction_limit_and_run_traceability(monkeypatch, clean_database):
    documents = [
        {"identificador": "BOE-2026-LIMIT-1", "fecha_publicacion": date(2026, 8, 1), "titulo": "Doc 1", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-LIMIT-2", "fecha_publicacion": date(2026, 8, 1), "titulo": "Doc 2", "seccion_codigo": "3"},
    ]
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_extraction_max_documents_per_run", 1)
    calls = []

    def fake_extractor(text, title):
        calls.append(title)
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador=f"ID-{len(calls)}", importe_deuda_eur=10)])

    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documents, fetch_text=lambda _: ("texto", "xml"),
        extractor=fake_extractor, send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    result = scraping.run_scraping("2026-08-01", permitir_extraccion_pago=True, dependencies=deps)
    assert len(calls) == 1  # limit=1 stops the second document's extraction
    assert result["extracted"] == 1

    session = SyncSessionLocal()
    try:
        run = session.execute(select(ScrapingRun).where(ScrapingRun.fecha_boe == date(2026, 8, 1))).scalar_one()
        assert run.extraction_requested is True
        assert run.extraction_provider == "openai"
        assert run.extraction_limit == 1
        assert run.extraction_attempts == 1
    finally:
        session.close()


@pytest.mark.integration
def test_scheduler_run_has_no_extraction_provider(monkeypatch, clean_database):
    """The daily scheduler call (no ``permitir_extraccion_pago``) must record a
    disabled provider and zero limit, even if OpenAI is enabled in config."""
    document = {
        "identificador": "BOE-2026-SCHED-1", "fecha_publicacion": date(2026, 8, 2), "titulo": "Doc", "seccion_codigo": "3",
    }
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto", "xml"),
        send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    scraping.run_scraping("2026-08-02", dependencies=deps)  # no permitir_extraccion_pago
    session = SyncSessionLocal()
    try:
        run = session.execute(select(ScrapingRun).where(ScrapingRun.fecha_boe == date(2026, 8, 2))).scalar_one()
        assert run.extraction_requested is False
        assert run.extraction_provider == "disabled"
        assert run.extraction_limit == 0
    finally:
        session.close()
