"""Cost-controlled BOE ingestion pipeline.

The Celery task is deliberately thin. ``run_scraping`` accepts a dependency
bundle so tests can exercise the complete flow with fixtures and zero network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import select, text

from app.celery_app import celery
from app.config import settings
from app.database import SyncSessionLocal, sync_engine
from app.models.documento import BoeDocumento
from app.models.scraping_run import ScrapingRun
from app.services.boe_client import fetch_document_content, fetch_document_pdf, fetch_sumario, flatten_sumario, hash_text
from app.services.classifier import classify_document, should_skip_section, verify_with_body
from app.services.extractor import ResultadoExtraccion, extract_sanctions
from app.services.notifier import create_inapp_notification, send_email_digest
from app.services.oportunidades import upsert_afectado
from app.services.parser import extract_text_from_document, pdf_to_text
from app.services.teu_client import MAX_TEU_PER_RUN, fetch_teu_index, fetch_teu_pdf, filter_relevant_teu_entries, parse_teu_index

logger = logging.getLogger(__name__)


class PaidExtractionNotAllowed(ValueError):
    """Raised when a manual request has not passed both cost-control gates."""


@dataclass(frozen=True)
class PipelineDependencies:
    fetch_sumario: Callable[[date], dict] = fetch_sumario
    flatten_sumario: Callable[[dict, date], list[dict[str, Any]]] = flatten_sumario
    fetch_text: Callable[[dict[str, Any]], tuple[str, str]] | None = None
    extractor: Callable[[str, str], ResultadoExtraccion] = extract_sanctions
    send_digest: Callable[[list, str], None] = send_email_digest
    notify: Callable[[Any, Any], None] = create_inapp_notification
    fetch_teu_index: Callable[[date], str] = fetch_teu_index
    parse_teu_index: Callable[[str, date], list[dict[str, Any]]] = parse_teu_index
    filter_teu_entries: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = filter_relevant_teu_entries
    fetch_teu_pdf: Callable[[str], bytes] = fetch_teu_pdf


def _fetch_text(doc_data: dict[str, Any]) -> tuple[str, str]:
    return extract_text_from_document(
        doc_data.get("url_xml"), doc_data.get("url_html"), doc_data.get("url_pdf"),
        fetch_fn=fetch_document_content, fetch_pdf_fn=fetch_document_pdf,
    )


def _get_text(deps: PipelineDependencies, doc_data: dict[str, Any]) -> tuple[str, str]:
    return (deps.fetch_text or _fetch_text)(doc_data)


def _guess_familia_from_section(doc_data: dict[str, Any]) -> str:
    sec = (doc_data.get("seccion_codigo") or "")
    if sec.startswith("5"):
        return "anuncio_expediente"
    if sec == "3":
        return "sancion_firme"
    if sec == "4":
        return "administracion_justicia"
    return "otro"


def _try_acquire_lock(db, target_date: date) -> bool:
    """Use a session-level PostgreSQL advisory lock for one BOE date."""
    value = db.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:key))"),
        {"key": f"boe-scraping:{target_date.isoformat()}"},
    ).scalar()
    return bool(value)


def _release_lock(db, target_date: date) -> None:
    db.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": f"boe-scraping:{target_date.isoformat()}"})


def _document_from_data(db, doc_data: dict[str, Any], text_value: str | None, source: str, confidence: float, rules: list[str], familia: str) -> BoeDocumento:
    document = BoeDocumento(
        boe_id=doc_data["identificador"],
        fecha_publicacion=doc_data["fecha_publicacion"],
        diario_numero=doc_data.get("diario_numero"),
        seccion_codigo=doc_data.get("seccion_codigo"),
        seccion_nombre=doc_data.get("seccion_nombre"),
        departamento_codigo=doc_data.get("departamento_codigo"),
        departamento_nombre=doc_data.get("departamento_nombre"),
        epigrafe_nombre=doc_data.get("epigrafe_nombre"),
        titulo=doc_data["titulo"],
        texto_plano=text_value[:50_000] if text_value else None,
        hash_texto=hash_text(text_value) if text_value else None,
        familia_sancionadora=familia,
        confidence=confidence,
        match_rules=rules,
        url_html=doc_data.get("url_html"),
        url_xml=doc_data.get("url_xml"),
        url_pdf=doc_data.get("url_pdf"),
        raw_sumario_item=doc_data.get("raw_item"),
        source=f"boe_api_{source}",
        extraction_status="pending",
    )
    db.add(document)
    db.flush()
    return document


def _extract_document(db, run: ScrapingRun, document: BoeDocumento, text_value: str, deps: PipelineDependencies, new_sancionados: list, stats: dict[str, int]) -> None:
    run.extraction_attempts += 1
    document.extraction_attempted_at = datetime.now(timezone.utc)
    document.extractor_version = f"openai:{settings.openai_model}"
    try:
        result = deps.extractor(text_value, document.titulo)
        for affected in result.afectados if result.es_documento_relevante else []:
            opportunity, created = upsert_afectado(db, document, affected)
            if opportunity is not None and created:
                deps.notify(db, opportunity)
                new_sancionados.append(opportunity)
                stats["extracted"] += 1
        document.extraction_status = "completed"
        document.extraction_error = None
    except Exception as exc:
        document.extraction_status = "error"
        document.extraction_error = str(exc)[:2_000]
        stats["errors"] += 1
        logger.exception("Structured extraction failed for %s", document.boe_id)


def _process_candidate(db, run, doc_data: dict[str, Any], text_value: str, source: str, rules: list[str], confidence: float, familia: str, allow_extraction: bool, limit: int, deps: PipelineDependencies, new_sancionados: list, stats: dict[str, int], force: bool) -> None:
    stats["candidates"] += 1
    existing = db.execute(select(BoeDocumento).where(BoeDocumento.boe_id == doc_data["identificador"])).scalar_one_or_none()
    document = existing or _document_from_data(db, doc_data, text_value, source, confidence, rules, familia)

    if existing and not document.texto_plano and text_value:
        document.texto_plano = text_value[:50_000]
        document.hash_texto = hash_text(text_value)

    if not allow_extraction:
        return
    if document.extraction_status == "completed" and not force:
        return
    if run.extraction_attempts >= limit:
        return
    effective_text = document.texto_plano or text_value
    if not effective_text:
        document.extraction_status = "error"
        document.extraction_error = "No se pudo obtener texto del documento"
        stats["errors"] += 1
        return
    _extract_document(db, run, document, effective_text, deps, new_sancionados, stats)


def _scrape_teu(db, run, target_date: date, allow_extraction: bool, limit: int, deps: PipelineDependencies, new_sancionados: list, stats: dict[str, int], force: bool) -> None:
    """Preserve TEU intake; extraction follows the same paid-cost policy."""
    entries = deps.filter_teu_entries(deps.parse_teu_index(deps.fetch_teu_index(target_date), target_date))
    stats["total_docs"] += len(entries)
    for entry in entries[:MAX_TEU_PER_RUN]:
        existing = db.execute(select(BoeDocumento).where(BoeDocumento.boe_id == entry["identificador"])).scalar_one_or_none()
        if existing and (not allow_extraction or (existing.extraction_status == "completed" and not force)):
            continue
        pdf = deps.fetch_teu_pdf(entry["url_pdf"])
        content = pdf_to_text(pdf)
        if not content:
            continue
        document = existing or BoeDocumento(
            boe_id=entry["identificador"], fecha_publicacion=entry["fecha_publicacion"],
            seccion_codigo="TEU", seccion_nombre="Tablón Edictal Único",
            departamento_nombre=entry.get("departamento_nombre"), titulo=entry["titulo"],
            texto_plano=content[:50_000], hash_texto=hash_text(content),
            familia_sancionadora="notificacion_teu", confidence=0.80,
            match_rules=["teu_title_match"], url_pdf=entry["url_pdf"], source="teu_pdf",
            extraction_status="pending",
        )
        if not existing:
            db.add(document)
            db.flush()
        _process_candidate(db, run, entry, content, "pdf", ["teu_title_match"], 0.80, "notificacion_teu", allow_extraction, limit, deps, new_sancionados, stats, force)


def run_scraping(fecha_str: str | None = None, force: bool = False, permitir_extraccion_pago: bool = False, dependencies: PipelineDependencies | None = None) -> dict[str, int | bool | str]:
    """Run one date with no paid extraction unless both gates are open."""
    target_date = date.fromisoformat(fecha_str) if fecha_str else date.today()
    deps = dependencies or PipelineDependencies()
    if permitir_extraccion_pago and (not settings.openai_extraction_enabled or not settings.openai_api_key):
        raise PaidExtractionNotAllowed("La extracción OpenAI requiere configuración habilitada y una API key.")
    allow_extraction = permitir_extraccion_pago and settings.openai_extraction_enabled and bool(settings.openai_api_key)
    limit = settings.openai_extraction_max_documents_per_run if allow_extraction else 0
    db = SyncSessionLocal()
    lock_connection = sync_engine.connect()
    stats: dict[str, int | bool | str] = {"total_docs": 0, "candidates": 0, "extracted": 0, "errors": 0, "scanned": 0, "openai_calls": 0}
    new_sancionados: list = []
    lock_acquired = False

    try:
        # Keep the session-level PostgreSQL lock on a dedicated connection.
        # The work session commits after each document, so it must not own it.
        lock_acquired = _try_acquire_lock(lock_connection, target_date)
        if not lock_acquired:
            return {**stats, "skipped": True, "reason": "already_running"}
        previous = db.execute(select(ScrapingRun).where(ScrapingRun.fecha_boe == target_date, ScrapingRun.status == "completed").order_by(ScrapingRun.id.desc())).scalar_one_or_none()
        if previous and not force and not allow_extraction:
            return {**stats, "skipped": True, "reason": f"already_completed (run #{previous.id})"}

        run = ScrapingRun(
            fecha_boe=target_date, status="running", started_at=datetime.now(timezone.utc),
            extraction_requested=allow_extraction, extraction_provider="openai" if allow_extraction else "disabled",
            extraction_limit=limit, extraction_attempts=0,
        )
        db.add(run)
        db.commit()

        payload = deps.fetch_sumario(target_date)
        docs = deps.flatten_sumario(payload, target_date)
        stats["total_docs"] = len(docs)
        for doc_data in docs:
            if not doc_data.get("identificador") or should_skip_section(doc_data):
                continue
            title_candidate, title_rules, title_confidence, familia = classify_document(doc_data)
            text_value, source = _get_text(deps, doc_data)
            stats["scanned"] += 1
            body_ok, body_rules = verify_with_body(text_value) if text_value else (False, [])
            if not title_candidate and not body_ok:
                continue
            rules = title_rules + body_rules if title_candidate else body_rules
            confidence = max(title_confidence, 0.85 if len(body_rules) >= 3 else 0.65) if title_candidate else (0.85 if len(body_rules) >= 3 else 0.65)
            _process_candidate(db, run, doc_data, text_value, source, rules, confidence, familia or _guess_familia_from_section(doc_data), allow_extraction, limit, deps, new_sancionados, stats, force)
            db.commit()

        # TEU is part of the existing daily intake. It is isolated so a source
        # issue cannot make an already persisted BOE run fail.
        try:
            _scrape_teu(db, run, target_date, allow_extraction, limit, deps, new_sancionados, stats, force)
        except Exception:
            logger.exception("TEU ingestion failed for %s", target_date)

        run.status = "completed"
        run.total_docs = int(stats["total_docs"])
        run.candidates = int(stats["candidates"])
        run.extracted = int(stats["extracted"])
        run.errors = int(stats["errors"])
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        if new_sancionados:
            deps.send_digest(new_sancionados, str(target_date))
        return {**stats, "openai_calls": run.extraction_attempts}
    except Exception as exc:
        db.rollback()
        logger.exception("Scraping pipeline failed for %s", target_date)
        return {**stats, "error": str(exc)}
    finally:
        if lock_acquired:
            try:
                _release_lock(lock_connection, target_date)
                lock_connection.commit()
            except Exception:
                pass
        lock_connection.close()
        db.close()


@celery.task(name="app.tasks.scraping.run_daily_scraping")
def run_daily_scraping(fecha_str: str | None = None, force: bool = False, permitir_extraccion_pago: bool = False) -> dict:
    return run_scraping(fecha_str, force, permitir_extraccion_pago)
