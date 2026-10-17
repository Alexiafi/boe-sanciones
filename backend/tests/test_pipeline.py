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


def _deps_minimas(documents, **overrides):
    base = dict(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documents, fetch_text=lambda _: ("texto", "xml", None),
        send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    base.update(overrides)
    return scraping.PipelineDependencies(**base)


@pytest.mark.integration
def test_unpublished_boe_edition_creates_no_run_row(clean_database):
    """A 404 from the BOE (edition not out yet, Sunday) is "nothing to do",
    not a failed run: the hourly beat retries and the UI shows no phantom."""
    from app.services.boe_client import BoeSumarioNoDisponible

    def _404(fecha):
        raise BoeSumarioNoDisponible(fecha)

    result = scraping.run_scraping("2026-09-13", dependencies=_deps_minimas([], fetch_sumario=_404))
    assert result["skipped"] is True and result["reason"] == "boe_no_publicado"
    session = SyncSessionLocal()
    try:
        assert session.execute(select(ScrapingRun)).scalars().all() == []
    finally:
        session.close()


@pytest.mark.integration
def test_pipeline_failure_marks_run_failed_with_error(clean_database):
    """Any other failure mid-run must leave a ``failed`` row with the error,
    never one stuck in ``running`` (which is what the old code did)."""

    def _boom(*_):
        raise RuntimeError("BOE devolvió basura")

    result = scraping.run_scraping("2026-09-14", dependencies=_deps_minimas([], flatten_sumario=_boom))
    assert "error" in result and "basura" in result["error"]
    session = SyncSessionLocal()
    try:
        run = session.execute(select(ScrapingRun)).scalars().one()
        assert run.status == "failed" and "basura" in (run.error_log or "") and run.finished_at is not None
    finally:
        session.close()


@pytest.mark.integration
def test_hung_runs_are_marked_failed_and_pending_dates_exclude_sundays(clean_database):
    from datetime import datetime, timedelta, timezone

    session = SyncSessionLocal()
    try:
        ahora = datetime.now(timezone.utc)
        session.add(ScrapingRun(fecha_boe=date(2026, 9, 15), tipo="diario", status="running", started_at=ahora - timedelta(hours=5)))
        session.add(ScrapingRun(fecha_boe=date(2026, 9, 16), tipo="diario", status="running", started_at=ahora - timedelta(minutes=10)))
        session.add(ScrapingRun(fecha_boe=date(2026, 9, 16), tipo="diario", status="completed", started_at=ahora))
        session.add(ScrapingRun(fecha_boe=date(2026, 9, 17), tipo="historico_cliente", status="completed", started_at=ahora))
        session.commit()

        assert scraping.marcar_runs_colgados(session, ahora=ahora) == 1
        rows = session.execute(select(ScrapingRun).order_by(ScrapingRun.id)).scalars().all()
        assert [r.status for r in rows] == ["failed", "running", "completed", "completed"]
        assert "interrumpida" in (rows[0].error_log or "")

        # Sept 13 2026 is a Sunday; 16 is completed; 17's only run is not "diario".
        pendientes = scraping.fechas_pendientes(session, hoy=date(2026, 9, 18), dias=7)
        assert pendientes == [date(2026, 9, 12), date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 17), date(2026, 9, 18)]
    finally:
        session.close()


@pytest.mark.integration
def test_teu_cap_comes_from_runtime_configuration(monkeypatch, clean_database):
    from app.services.configuracion import ConfiguracionRuntime

    entries = [
        {"identificador": f"BOE-N-2026-{i}", "fecha_publicacion": date(2026, 9, 7), "titulo": f"TEU {i}", "url_pdf": f"/pdf/{i}"}
        for i in range(5)
    ]
    monkeypatch.setattr(scraping, "pdf_to_text", lambda _pdf: "Expediente sancionador. Multa. Infracción.")
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    deps = _deps_minimas(
        [], fetch_teu_index=lambda _: "html", parse_teu_index=lambda *_: entries, filter_teu_entries=lambda e: e,
        fetch_teu_pdf=lambda _: b"%PDF", leer_configuracion=lambda _db: ConfiguracionRuntime(teu_max_por_ejecucion=2),
    )
    result = scraping.run_scraping("2026-09-07", dependencies=deps)
    assert result["candidates"] == 2 and result["total_docs"] == 5


@pytest.mark.integration
def test_long_extracted_values_are_truncated_and_bad_rows_do_not_poison_the_run(monkeypatch, clean_database):
    """Seen in production: the model returned a 300-character ``plazo`` and
    the flush error aborted the document AND left the session unusable for
    the rest of the run (TEU ingestion then failed too)."""
    from app.services import oportunidades

    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_extraction_max_documents_per_run", 10)

    largo = "Plazo " * 100  # 600 chars > String(200)
    documents = [
        {"identificador": "BOE-2026-LONG-1", "fecha_publicacion": date(2026, 9, 8), "titulo": "Doc 1", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-LONG-2", "fecha_publicacion": date(2026, 9, 8), "titulo": "Doc 2", "seccion_codigo": "3"},
    ]

    def extractor(text, title):
        if title == "Doc 1":
            return ResultadoExtraccion(afectados=[
                AfectadoExtraido(identificador="B00000001", plazo_alegaciones=largo, expediente="X" * 250),
                AfectadoExtraido(identificador="ROMPE", nombre="Fila que rompe"),
                AfectadoExtraido(identificador="B00000002", nombre="Tercero"),
            ])
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador="B00000003")])

    original = oportunidades.upsert_afectado

    def upsert_que_rompe(session, boe_doc, data):
        if data.identificador == "ROMPE":
            from sqlalchemy import text as sql_text
            session.execute(sql_text("INSERT INTO sancionados (id) VALUES (NULL)"))  # guaranteed constraint failure
        return original(session, boe_doc, data)

    monkeypatch.setattr(scraping, "upsert_afectado", upsert_que_rompe)

    deps = _deps_minimas(documents, extractor=extractor)
    result = scraping.run_scraping("2026-09-08", permitir_extraccion_pago=True, dependencies=deps)
    assert result["extracted"] == 3 and result["errors"] == 0

    session = SyncSessionLocal()
    try:
        filas = {s.identificador: s for s in session.execute(select(Sancionado)).scalars().all()}
        assert set(filas) == {"B00000001", "B00000002", "B00000003"}
        assert len(filas["B00000001"].plazo_alegaciones) == 200
        assert len(filas["B00000001"].expediente) == 200
        docs = {d.boe_id: d for d in session.execute(select(BoeDocumento)).scalars().all()}
        assert docs["BOE-2026-LONG-1"].extraction_status == "completed"
        assert "1 afectado(s)" in (docs["BOE-2026-LONG-1"].extraction_error or "")
        assert docs["BOE-2026-LONG-2"].extraction_status == "completed"
        run = session.execute(select(ScrapingRun)).scalars().one()
        assert run.status == "completed"
    finally:
        session.close()


@pytest.mark.integration
def test_errored_documents_get_one_automatic_retry_then_only_force(monkeypatch, clean_database):
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_extraction_max_documents_per_run", 10)
    documents = [{"identificador": "BOE-2026-RETRY", "fecha_publicacion": date(2026, 9, 9), "titulo": "Doc", "seccion_codigo": "3"}]
    calls: list[int] = []

    def extractor(text, title):
        calls.append(1)
        raise RuntimeError("OpenAI caído")

    deps = _deps_minimas(documents, extractor=extractor)
    first = scraping.run_scraping("2026-09-09", permitir_extraccion_pago=None, dependencies=deps)
    assert first["errors"] == 1 and len(calls) == 1
    second = scraping.run_scraping("2026-09-09", permitir_extraccion_pago=None, dependencies=deps)
    assert second["errors"] == 1 and len(calls) == 2  # the one automatic retry
    third = scraping.run_scraping("2026-09-09", permitir_extraccion_pago=None, dependencies=deps)
    assert third.get("skipped") is True and len(calls) == 2  # no more hourly spending
    forced = scraping.run_scraping("2026-09-09", permitir_extraccion_pago=True, force=True, dependencies=deps)
    assert forced["errors"] == 1 and len(calls) == 3


@pytest.mark.integration
def test_one_failing_document_does_not_abort_the_rest_of_the_day(monkeypatch, clean_database):
    """Seen in production: a 502 on one TEU PDF aborted the remaining ~900
    notices of the day. Each BOE document and each TEU notice must fail alone."""
    from app.services.configuracion import ConfiguracionRuntime

    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    monkeypatch.setattr(scraping, "pdf_to_text", lambda _pdf: "Expediente sancionador. Multa. Infracción.")
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    documents = [
        {"identificador": "BOE-2026-ISO-1", "fecha_publicacion": date(2026, 9, 10), "titulo": "Doc 1", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-ISO-2", "fecha_publicacion": date(2026, 9, 10), "titulo": "Doc 2", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-ISO-3", "fecha_publicacion": date(2026, 9, 10), "titulo": "Doc 3", "seccion_codigo": "3"},
    ]
    entries = [
        {"identificador": f"BOE-N-2026-ISO-{i}", "fecha_publicacion": date(2026, 9, 10), "titulo": f"TEU {i}", "url_pdf": f"/pdf/{i}"}
        for i in range(4)
    ]

    def fetch_text(doc_data):
        if doc_data["identificador"].endswith("-2"):
            raise RuntimeError("502 Bad Gateway")
        return ("texto", "xml", None)

    def fetch_pdf(url):
        if url.endswith("/1"):
            raise RuntimeError("502 Bad Gateway")
        return b"%PDF"

    calls: list[str] = []

    def extractor(text, title):
        calls.append(title)
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador=f"ID-{title}")])

    deps = _deps_minimas(
        documents, fetch_text=fetch_text, extractor=extractor,
        fetch_teu_index=lambda _: "html", parse_teu_index=lambda *_: entries, filter_teu_entries=lambda e: e,
        fetch_teu_pdf=fetch_pdf, leer_configuracion=lambda _db: ConfiguracionRuntime(extraccion_max_docs_por_ejecucion=50),
    )
    result = scraping.run_scraping("2026-09-10", permitir_extraccion_pago=True, dependencies=deps)
    assert result["errors"] == 2
    assert result["extracted"] == 5  # 2 BOE docs + 3 TEU notices
    assert sorted(calls) == ["Doc 1", "Doc 3", "TEU 0", "TEU 2", "TEU 3"]

    session = SyncSessionLocal()
    try:
        run = session.execute(select(ScrapingRun)).scalars().one()
        assert run.status == "completed" and run.errors == 2 and run.extracted == 5
    finally:
        session.close()

    # A forced re-run picks up what failed (the sources are back) without
    # paying again for what is already extracted.
    ok_deps = _deps_minimas(
        documents, extractor=extractor,
        fetch_teu_index=lambda _: "html", parse_teu_index=lambda *_: entries, filter_teu_entries=lambda e: e,
        fetch_teu_pdf=lambda _: b"%PDF", leer_configuracion=lambda _db: ConfiguracionRuntime(extraccion_max_docs_por_ejecucion=50),
    )
    again = scraping.run_scraping("2026-09-10", permitir_extraccion_pago=True, force=True, dependencies=ok_deps)
    assert again["errors"] == 0 and again["extracted"] == 2
    assert sorted(calls) == ["Doc 1", "Doc 2", "Doc 3", "TEU 0", "TEU 1", "TEU 2", "TEU 3"]
