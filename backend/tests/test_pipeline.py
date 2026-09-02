from __future__ import annotations

from datetime import date
import os

import pytest

from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.cliente import Cliente
from app.models.documento import BoeDocumento
from app.models.scraping_run import ScrapingRun
from app.models.sancionado import Sancionado
from app.services import extractor as extractor_module
from app.services.extractor import AfectadoExtraido, ResultadoExtraccion
from app.services.oportunidades import allocate_codigo
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
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto de fixture", "xml", None),
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
def test_pipeline_auto_assigns_new_sancion_to_existing_client(monkeypatch, clean_database):
    """Vía A of the client-alert feature: a newly extracted sanción whose
    identificador matches an existing client gets attached automatically,
    with the client-alert notification and 'sistema' activity that implies."""
    document = {
        "identificador": "BOE-2026-TEST-CLI", "fecha_publicacion": date(2026, 8, 2),
        "titulo": "Documento cliente existente", "seccion_codigo": "3",
    }
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    session = SyncSessionLocal()
    try:
        origen_doc = BoeDocumento(boe_id="BOE-CLI-ORIGEN", fecha_publicacion=date(2026, 1, 1), titulo="Origen")
        session.add(origen_doc)
        session.flush()
        origen_sancionado = Sancionado(
            boe_document_id=origen_doc.id, codigo=allocate_codigo(session, 2026),
            estado_oportunidad="cliente", origen_clave="clave-cliente-existente", nombre="Acme Logistica SL",
        )
        session.add(origen_sancionado)
        session.flush()
        cliente = Cliente(
            codigo="CLI-2026-9001", nombre_razon_social="Acme Logistica SL", cif_nif="B12345678",
            sancion_origen_id=origen_sancionado.id,
        )
        session.add(cliente)
        session.commit()
        cliente_id = cliente.id
    finally:
        session.close()

    def fake_extractor(text, title):
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador="B12345678", nombre="Acme Logistica SL")])

    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto de fixture", "xml", None),
        extractor=fake_extractor, send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    result = scraping.run_scraping("2026-08-02", permitir_extraccion_pago=True, dependencies=deps)
    assert result["extracted"] == 1
    assert result["clientes_asignados"] == 1

    session = SyncSessionLocal()
    try:
        nueva = session.execute(
            select(Sancionado).where(Sancionado.origen_clave != "clave-cliente-existente")
        ).scalars().all()
        assert len(nueva) == 1
        assert nueva[0].cliente_id == cliente_id
        assert nueva[0].estado_oportunidad == "cliente"
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
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto", "xml", None),
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
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documents, fetch_text=lambda _: ("texto", "xml", None),
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
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document], fetch_text=lambda _: ("texto", "xml", None),
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
