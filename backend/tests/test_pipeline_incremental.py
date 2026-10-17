"""The daily pipeline after the "3 hours / days that never download" report:
parallel extraction, incremental re-runs, late TEU notices, liveness, catch-up."""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.scraping_run import ScrapingRun
from app.services.configuracion import ConfiguracionRuntime
from app.services.extractor import AfectadoExtraido, ResultadoExtraccion
from app.tasks import scraping

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


@pytest.fixture(autouse=True)
def _pipeline_abierto(monkeypatch):
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda d: (d["titulo"] != "IRRELEVANTE", ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (False, []))
    monkeypatch.setattr(scraping, "pdf_to_text", lambda _pdf: "Expediente sancionador. Multa. Infracción.")
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_extraction_max_documents_per_run", 500)
    monkeypatch.setattr(settings, "openai_concurrency", 4)


def _docs(hoy: date, titulos: list[str]) -> list[dict]:
    return [
        {"identificador": f"BOE-INC-{hoy:%m%d}-{i}", "fecha_publicacion": hoy, "titulo": titulo, "seccion_codigo": "3"}
        for i, titulo in enumerate(titulos)
    ]


def _deps(documentos, extractor, *, fetch_text=None, teu=None, config=None):
    entradas = teu if teu is not None else []
    return scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documentos,
        fetch_text=fetch_text or (lambda d: (f"texto de {d['identificador']}", "xml", None)),
        extractor=extractor, send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "html", parse_teu_index=lambda *_: list(entradas), filter_teu_entries=lambda e: e,
        fetch_teu_pdf=lambda _: b"%PDF",
        leer_configuracion=lambda _db: config or ConfiguracionRuntime(extraccion_max_docs_por_ejecucion=500),
    )


def _uno(identificador):
    return lambda texto, titulo: ResultadoExtraccion(afectados=[AfectadoExtraido(identificador=identificador(titulo))])


# --- parallel extraction -------------------------------------------------------

@pytest.mark.integration
def test_openai_calls_run_concurrently_not_one_after_another(monkeypatch, clean_database):
    """A day took 3+ hours because every document waited for the previous
    OpenAI call. Three calls that can only finish together prove they overlap
    (sequential execution would break the barrier)."""
    monkeypatch.setattr(settings, "openai_concurrency", 3)
    barrera = threading.Barrier(3, timeout=10)

    def extractor(texto, titulo):
        barrera.wait()
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador=f"B{titulo[-1]}2345678")])

    resultado = scraping.run_scraping(
        "2026-09-01", permitir_extraccion_pago=True, dependencies=_deps(_docs(date(2026, 9, 1), ["Doc 1", "Doc 2", "Doc 3"]), extractor),
    )
    assert resultado["errors"] == 0 and resultado["extracted"] == 3


@pytest.mark.integration
def test_traffic_notices_are_extracted_first(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "openai_concurrency", 1)
    orden: list[str] = []

    def extractor(texto, titulo):
        orden.append(titulo)
        return ResultadoExtraccion(afectados=[])

    titulos = ["Expediente de subvención", "Notificaciones de denuncia", "Providencia de apremio", "Jefatura Provincial de Tráfico"]
    scraping.run_scraping("2026-09-02", permitir_extraccion_pago=True, dependencies=_deps(_docs(date(2026, 9, 2), titulos), extractor))
    assert orden[:2] == ["Notificaciones de denuncia", "Jefatura Provincial de Tráfico"]
    assert sorted(orden) == sorted(titulos)


@pytest.mark.integration
def test_extraction_stops_after_consecutive_failures_and_leaves_the_rest_untouched(monkeypatch, clean_database):
    """A revoked key / exhausted quota must not fail (and bill retries for) the
    whole day; documents never attempted stay pending for the next run."""
    monkeypatch.setattr(settings, "openai_concurrency", 1)
    llamadas: list[str] = []

    def caido(texto, titulo):
        llamadas.append(titulo)
        raise RuntimeError("insufficient_quota")

    resultado = scraping.run_scraping(
        "2026-09-03", permitir_extraccion_pago=True,
        dependencies=_deps(_docs(date(2026, 9, 3), [f"Doc {i}" for i in range(20)]), caido),
    )
    assert scraping.MAX_FALLOS_SEGUIDOS <= len(llamadas) <= scraping.MAX_FALLOS_SEGUIDOS + 2
    assert resultado["extraccion_detenida"] is True
    session = SyncSessionLocal()
    try:
        estados = [d.extraction_status for d in session.execute(select(BoeDocumento)).scalars().all()]
        assert estados.count("error") == len(llamadas) and estados.count("pending") == 20 - len(llamadas)
        run = session.execute(select(ScrapingRun)).scalars().one()
        assert run.status == "completed" and "detenida" in run.error_log and run.extraction_attempts == len(llamadas)
        intentos = {d.extraction_status: d.extraction_intentos for d in session.execute(select(BoeDocumento)).scalars().all()}
        assert intentos["pending"] == 0 and intentos["error"] == 1
    finally:
        session.close()


# --- incremental runs ----------------------------------------------------------

@pytest.mark.integration
def test_late_teu_notices_are_picked_up_by_a_rerun_without_redownloading_the_day(clean_database):
    """The TEU supplement can appear after the first run of the day. The re-run
    must add it — and must not re-download what is already stored."""
    hoy = date.today()
    descargas: list[str] = []

    def fetch_text(doc):
        descargas.append(doc["identificador"])
        return (f"texto de {doc['identificador']}", "xml", None)

    documentos = _docs(hoy, ["Doc A"])
    extractor = _uno(lambda titulo: f"B1{abs(hash(titulo)) % 10**6:06d}7")
    primera = scraping.run_scraping(hoy.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text, teu=[]))
    assert primera["candidates"] == 1 and descargas == [documentos[0]["identificador"]]

    entradas = [
        {"identificador": f"BOE-N-INC-{i}", "fecha_publicacion": hoy, "titulo": f"TEU {i}", "url_pdf": f"/pdf/{i}"} for i in range(2)
    ]
    segunda = scraping.run_scraping(hoy.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text, teu=entradas))
    assert segunda["candidates"] == 2 and segunda["extracted"] == 2
    assert descargas == [documentos[0]["identificador"]]       # the BOE document was not fetched again

    tercera = scraping.run_scraping(hoy.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text, teu=entradas))
    assert tercera.get("skipped") is True
    session = SyncSessionLocal()
    try:
        assert len(session.execute(select(ScrapingRun)).scalars().all()) == 2     # nothing new: no phantom run
    finally:
        session.close()


@pytest.mark.integration
def test_a_rerun_after_errors_fetches_only_what_failed(clean_database):
    """Documents judged "not a candidate" are never stored; without a record of
    having looked at them every re-run would download them all again."""
    dia = date(2026, 9, 4)
    documentos = _docs(dia, ["Candidato", "IRRELEVANTE", "Falla la primera vez"])
    descargas: list[str] = []
    fallar = {"activo": True}

    def fetch_text(doc):
        descargas.append(doc["titulo"])
        if doc["titulo"] == "Falla la primera vez" and fallar["activo"]:
            raise RuntimeError("502 Bad Gateway")
        return ("texto", "xml", None)

    extractor = _uno(lambda titulo: f"B2{abs(hash(titulo)) % 10**6:06d}8")
    primera = scraping.run_scraping(dia.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text))
    assert primera["errors"] == 1 and sorted(descargas) == ["Candidato", "Falla la primera vez", "IRRELEVANTE"]

    descargas.clear()
    fallar["activo"] = False
    segunda = scraping.run_scraping(dia.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text))
    assert descargas == ["Falla la primera vez"]
    assert segunda["errors"] == 0 and segunda["extracted"] == 1


@pytest.mark.integration
def test_run_reports_progress_and_heartbeat(clean_database):
    dia = date(2026, 9, 5)
    scraping.run_scraping(
        dia.isoformat(), permitir_extraccion_pago=True,
        dependencies=_deps(_docs(dia, ["Doc 1", "Doc 2"]), _uno(lambda titulo: f"B3{abs(hash(titulo)) % 10**6:06d}9")),
    )
    session = SyncSessionLocal()
    try:
        run = session.execute(select(ScrapingRun)).scalars().one()
        assert run.status == "completed" and run.fase == "completado"
        assert run.heartbeat_at is not None and run.progreso_total == 2 and run.progreso_actual == 2
        assert sorted(run.ids_revisados) == sorted(d["identificador"] for d in _docs(dia, ["Doc 1", "Doc 2"]))
        assert all(d.extraction_intentos == 1 for d in session.execute(select(BoeDocumento)).scalars().all())
    finally:
        session.close()


# --- liveness and catch-up -----------------------------------------------------

@pytest.mark.integration
def test_a_slow_run_with_a_fresh_heartbeat_is_not_declared_hung(clean_database):
    ahora = datetime.now(timezone.utc)
    session = SyncSessionLocal()
    try:
        viva = ScrapingRun(fecha_boe=date(2026, 9, 6), tipo="diario", status="running", started_at=ahora - timedelta(hours=5), heartbeat_at=ahora - timedelta(minutes=1))
        muerta = ScrapingRun(fecha_boe=date(2026, 9, 7), tipo="diario", status="running", started_at=ahora - timedelta(hours=1), heartbeat_at=ahora - timedelta(minutes=40))
        session.add_all([viva, muerta])
        session.commit()
        assert scraping.marcar_runs_colgados(session, ahora=ahora) == 1
        assert viva.status == "running" and muerta.status == "failed"
    finally:
        session.close()


@pytest.mark.integration
def test_catch_up_also_revisits_days_with_extraction_still_due_newest_first(monkeypatch, clean_database):
    hoy = date.today()
    ayer, antes = hoy - timedelta(days=1), hoy - timedelta(days=3)
    session = SyncSessionLocal()
    try:
        for dia in (ayer, antes):
            session.add(ScrapingRun(fecha_boe=dia, tipo="diario", status="completed", started_at=datetime.now(timezone.utc)))
            session.add(BoeDocumento(boe_id=f"BOE-CU-{dia:%m%d}", fecha_publicacion=dia, titulo="Doc", texto_plano="t", extraction_status="pending"))
        # a day beyond the retry limit and a completed one are not revisited
        session.add(BoeDocumento(boe_id="BOE-CU-agotado", fecha_publicacion=hoy - timedelta(days=2), titulo="D", extraction_status="error", extraction_intentos=scraping.MAX_INTENTOS_CON_ESPERA))
        session.add(BoeDocumento(boe_id="BOE-CU-hecho", fecha_publicacion=hoy - timedelta(days=4), titulo="D", extraction_status="completed"))
        session.commit()
        assert scraping.fechas_con_extraccion_pendiente(session, hoy=hoy) == [antes, ayer]
    finally:
        session.close()

    encoladas: list[str] = []
    monkeypatch.setattr(scraping.run_daily_scraping, "delay", lambda fecha, *a, **k: encoladas.append(fecha))
    scraping.catch_up_scraping()
    # newest first: yesterday's calls matter more than last week's
    assert encoladas.index(ayer.isoformat()) < encoladas.index(antes.isoformat())
    assert hoy.isoformat() in encoladas or hoy.weekday() == 6


@pytest.mark.integration
def test_only_a_few_automatic_retries_but_a_later_attempt_after_the_wait(clean_database):
    ahora = datetime.now(timezone.utc)
    doc = BoeDocumento(boe_id="BOE-X", fecha_publicacion=date(2026, 9, 8), titulo="D", extraction_status="error")
    doc.extraction_intentos, doc.extraction_attempted_at = 2, ahora - timedelta(minutes=10)
    assert scraping._intento_automatico_permitido(doc, ahora) is False
    doc.extraction_attempted_at = ahora - scraping.ESPERA_REINTENTO - timedelta(minutes=1)
    assert scraping._intento_automatico_permitido(doc, ahora) is True       # an outage that lasted hours heals itself
    doc.extraction_intentos = scraping.MAX_INTENTOS_CON_ESPERA
    assert scraping._intento_automatico_permitido(doc, ahora) is False
    doc.extraction_intentos = 1
    assert scraping._intento_automatico_permitido(doc, ahora) is True


# --- documents that never download / never have text ------------------------------

@pytest.mark.integration
def test_a_document_that_keeps_failing_is_given_up_on_instead_of_a_run_every_pass(clean_database):
    """One permanently broken document made every half-hourly pass download it
    again and record a new run (and an error) forever."""
    hoy = date.today()
    documentos = _docs(hoy, ["Bueno", "Roto"])
    intentos: list[str] = []

    def fetch_text(doc):
        if doc["titulo"] == "Roto":
            intentos.append("roto")
            raise RuntimeError("404")
        return ("texto", "xml", None)

    extractor = _uno(lambda titulo: f"B4{abs(hash(titulo)) % 10**6:06d}1")
    for _ in range(scraping.MAX_FALLOS_DESCARGA + 3):
        scraping.run_scraping(hoy.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text))
    assert len(intentos) == scraping.MAX_FALLOS_DESCARGA        # then it stops trying
    session = SyncSessionLocal()
    try:
        runs = session.execute(select(ScrapingRun)).scalars().all()
        assert len(runs) == scraping.MAX_FALLOS_DESCARGA        # and stops recording runs
    finally:
        session.close()
    # a forced run still retries it
    scraping.run_scraping(hoy.isoformat(), force=True, permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text))
    assert len(intentos) == scraping.MAX_FALLOS_DESCARGA + 1


@pytest.mark.integration
def test_a_teu_pdf_without_text_is_not_downloaded_again_every_pass(clean_database):
    hoy = date.today()
    descargas: list[str] = []
    entradas = [{"identificador": "BOE-N-INC-SCAN", "fecha_publicacion": hoy, "titulo": "TEU escaneado", "url_pdf": "/pdf/scan"}]

    def deps_con(entradas):
        base = _deps([], _uno(lambda titulo: "B5000000X"), teu=entradas)
        return scraping.PipelineDependencies(**{**base.__dict__, "fetch_teu_pdf": lambda url: descargas.append(url) or b"%PDF"})

    original = scraping.pdf_to_text
    scraping.pdf_to_text = lambda _pdf: ""          # a scanned PDF: nothing to extract
    try:
        for _ in range(4):
            scraping.run_scraping(hoy.isoformat(), permitir_extraccion_pago=True, dependencies=deps_con(entradas))
    finally:
        scraping.pdf_to_text = original
    assert descargas == ["/pdf/scan"]
    session = SyncSessionLocal()
    try:
        assert len(session.execute(select(ScrapingRun)).scalars().all()) == 1
    finally:
        session.close()


@pytest.mark.integration
def test_a_document_without_text_is_not_reselected_and_recovers_when_the_text_arrives(clean_database):
    dia = date(2026, 9, 11)
    documentos = _docs(dia, ["Sin texto al principio"])
    llamadas: list[str] = []
    estado = {"texto": ""}

    def fetch_text(doc):
        return (estado["texto"], "xml", None)

    def extractor(texto, titulo):
        llamadas.append(texto)
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador="B6000000Y")])

    primera = scraping.run_scraping(dia.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text))
    assert llamadas == [] and primera["errors"] >= 1
    session = SyncSessionLocal()
    try:
        doc = session.execute(select(BoeDocumento)).scalars().one()
        assert doc.extraction_status == "error" and doc.extraction_error == scraping.SIN_TEXTO
        assert doc.extraction_intentos == scraping.MAX_INTENTOS_CON_ESPERA       # exhausted: not selected again
        assert scraping.fechas_con_extraccion_pendiente(session, hoy=dia) == []   # nor does it pull the day into every catch-up
    finally:
        session.close()

    estado["texto"] = "ahora sí hay texto"
    segunda = scraping.run_scraping(dia.isoformat(), permitir_extraccion_pago=True, dependencies=_deps(documentos, extractor, fetch_text=fetch_text))
    assert llamadas == ["ahora sí hay texto"] and segunda["extracted"] == 1


@pytest.mark.integration
def test_a_zero_cap_pauses_paid_extraction_without_recording_empty_runs(clean_database):
    dia = date(2026, 9, 12)
    documentos = _docs(dia, ["Doc"])
    llamadas: list[str] = []
    pausado = ConfiguracionRuntime(extraccion_max_docs_por_ejecucion=0)
    primera = scraping.run_scraping(
        dia.isoformat(), permitir_extraccion_pago=None,
        dependencies=_deps(documentos, lambda t, ti: llamadas.append(ti) or ResultadoExtraccion(afectados=[]), config=pausado),
    )
    assert primera["modo_extraccion"] == "sin_extraccion" and llamadas == []
    segunda = scraping.run_scraping(
        dia.isoformat(), permitir_extraccion_pago=None,
        dependencies=_deps(documentos, lambda t, ti: llamadas.append(ti) or ResultadoExtraccion(afectados=[]), config=pausado),
    )
    assert segunda.get("skipped") is True and llamadas == []
