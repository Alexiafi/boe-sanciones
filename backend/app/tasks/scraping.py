"""Celery tasks for the BOE scraping pipeline."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.celery_app import celery
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.models.scraping_run import ScrapingRun
from app.services.boe_client import (
    fetch_document_content,
    fetch_document_pdf,
    fetch_sumario,
    flatten_sumario,
    hash_text,
)
from app.services.classifier import classify_document, should_skip_section, verify_with_body
from app.services.extractor import extract_sanctions
from app.services.notifier import create_inapp_notification, send_email_digest
from app.services.parser import extract_text_from_document, pdf_to_text
from app.services.teu_client import (
    MAX_TEU_PER_RUN,
    fetch_teu_index,
    fetch_teu_pdf,
    filter_relevant_teu_entries,
    parse_teu_index,
)

logger = logging.getLogger(__name__)


@celery.task(name="app.tasks.scraping.run_daily_scraping")
def run_daily_scraping(fecha_str: str | None = None, force: bool = False) -> dict:
    """
    Main pipeline: fetch BOE summary, classify all docs in relevant sections,
    download body text, verify with body patterns, extract with OpenAI.

    If a completed run already exists for the given date, it is skipped
    unless ``force=True``.
    """
    target_date = date.fromisoformat(fecha_str) if fecha_str else date.today()
    logger.info("Starting BOE scraping for %s", target_date)

    db = SyncSessionLocal()

    if not force:
        prev_run = db.execute(
            select(ScrapingRun).where(
                ScrapingRun.fecha_boe == target_date,
                ScrapingRun.status == "completed",
            )
        ).scalar_one_or_none()
        if prev_run:
            logger.info(
                "Skipping %s: already completed on run #%d (%d extracted). "
                "Use force=True to re-run.",
                target_date, prev_run.id, prev_run.extracted or 0,
            )
            db.close()
            return {
                "total_docs": 0, "candidates": 0, "extracted": 0,
                "errors": 0, "scanned": 0, "skipped": True,
                "reason": f"already_completed (run #{prev_run.id})",
            }

    run = ScrapingRun(
        fecha_boe=target_date,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()

    stats = {"total_docs": 0, "candidates": 0, "extracted": 0, "errors": 0, "scanned": 0}
    new_sancionados: list[Sancionado] = []

    try:
        payload = fetch_sumario(target_date)
        docs = flatten_sumario(payload, target_date)
        stats["total_docs"] = len(docs)

        for doc_data in docs:
            try:
                boe_id = doc_data.get("identificador")
                if not boe_id:
                    continue

                if should_skip_section(doc_data):
                    continue

                existing = db.execute(
                    select(BoeDocumento).where(BoeDocumento.boe_id == boe_id)
                ).scalar_one_or_none()
                if existing:
                    continue

                is_title_candidate, title_rules, title_conf, familia = classify_document(doc_data)

                if is_title_candidate and title_conf >= 0.9:
                    text, source = _fetch_text(doc_data)
                    if text:
                        body_ok, body_signals = verify_with_body(text)
                        if not body_ok:
                            logger.debug("Strong title match %s disqualified by body check", boe_id)
                            continue
                        title_rules.extend(body_signals)
                    _process_candidate(
                        db, doc_data, text, source, title_rules, title_conf, familia,
                        new_sancionados, stats,
                    )
                    time.sleep(0.1)
                    continue

                # Download body text for all non-skipped sections and check for keywords
                stats["scanned"] += 1
                text, source = _fetch_text(doc_data)
                if not text:
                    continue

                body_ok, body_signals = verify_with_body(text)

                if body_ok:
                    rules = body_signals
                    if is_title_candidate:
                        rules = title_rules + body_signals
                    confidence = 0.85 if len(body_signals) >= 3 else 0.65
                    if is_title_candidate:
                        confidence = max(confidence, title_conf)
                    familia_final = familia or _guess_familia_from_section(doc_data)
                    _process_candidate(
                        db, doc_data, text, source, rules, confidence, familia_final,
                        new_sancionados, stats,
                    )
                elif is_title_candidate:
                    text_for_extract = text if text else None
                    _process_candidate(
                        db, doc_data, text_for_extract, source, title_rules, title_conf, familia,
                        new_sancionados, stats,
                    )

                time.sleep(0.1)

            except Exception:
                stats["errors"] += 1
                db.rollback()
                logger.exception("Error processing document %s", doc_data.get("identificador"))

        # Phase 2: scrape TEU (Tablón Edictal Único) for notifications
        try:
            teu_stats = _scrape_teu(db, target_date, new_sancionados, stats)
            logger.info("TEU scraping: %s", teu_stats)
        except Exception:
            logger.exception("TEU scraping failed for %s (non-fatal)", target_date)

        if new_sancionados:
            send_email_digest(new_sancionados, str(target_date))

        run.status = "completed"
        run.total_docs = stats["total_docs"]
        run.candidates = stats["candidates"]
        run.extracted = stats["extracted"]
        run.errors = stats["errors"]
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            "Scraping done: %d docs, %d scanned, %d candidates, %d extracted, %d errors",
            stats["total_docs"], stats["scanned"], stats["candidates"],
            stats["extracted"], stats["errors"],
        )

    except Exception as e:
        run.status = "failed"
        run.error_log = str(e)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception("Scraping pipeline failed for %s", target_date)

    finally:
        db.close()

    return stats


def _fetch_text(doc_data: dict) -> tuple[str, str]:
    return extract_text_from_document(
        doc_data.get("url_xml"),
        doc_data.get("url_html"),
        doc_data.get("url_pdf"),
        fetch_fn=fetch_document_content,
        fetch_pdf_fn=fetch_document_pdf,
    )


def _guess_familia_from_section(doc_data: dict) -> str:
    sec = (doc_data.get("seccion_codigo") or "")
    if sec.startswith("5"):
        return "anuncio_expediente"
    if sec == "3":
        return "sancion_firme"
    if sec == "4":
        return "administracion_justicia"
    return "otro"


def _save_afectados(db, boe_doc, afectados, new_sancionados, stats):
    """Persist extracted entities, deduplicating within the same document."""
    seen: set[tuple[str, str | None]] = set()
    for s_data in afectados:
        if not s_data.nombre:
            continue
        key = (s_data.nombre.strip().upper(), (s_data.identificador or "").strip().upper() or None)
        if key in seen:
            continue
        seen.add(key)

        sancionado = Sancionado(
            boe_document_id=boe_doc.id,
            nombre=s_data.nombre,
            tipo_persona=s_data.tipo_persona,
            identificador=s_data.identificador,
            tipo_identificador=s_data.tipo_identificador,
            direccion=s_data.direccion,
            telefono=s_data.telefono,
            email=s_data.email,
            matricula_coche=s_data.matricula_coche,
            importe_multa_eur=float(s_data.importe_multa_eur) if s_data.importe_multa_eur else None,
            tipo_infraccion=s_data.tipo_infraccion,
            razon_sancion=s_data.razon_sancion,
            expediente=s_data.expediente,
            estado_publicacion=s_data.estado_publicacion,
            plazo_notificacion=s_data.plazo_notificacion,
            plazo_alegaciones=s_data.plazo_alegaciones,
            plazo_recurso=s_data.plazo_recurso,
            base_legal=s_data.base_legal,
            organismo_emisor=s_data.organismo_emisor,
            dominio_material=s_data.dominio_material,
        )
        db.add(sancionado)
        db.flush()

        create_inapp_notification(db, sancionado)
        new_sancionados.append(sancionado)
        stats["extracted"] += 1


def _process_candidate(
    db, doc_data, text, source, rules, confidence, familia,
    new_sancionados, stats,
):
    stats["candidates"] += 1
    boe_id = doc_data["identificador"]
    logger.info("Processing candidate %s (conf=%.2f, rules=%s)", boe_id, confidence, rules[:3])

    boe_doc = BoeDocumento(
        boe_id=boe_id,
        fecha_publicacion=doc_data["fecha_publicacion"],
        diario_numero=doc_data.get("diario_numero"),
        seccion_codigo=doc_data.get("seccion_codigo"),
        seccion_nombre=doc_data.get("seccion_nombre"),
        departamento_codigo=doc_data.get("departamento_codigo"),
        departamento_nombre=doc_data.get("departamento_nombre"),
        epigrafe_nombre=doc_data.get("epigrafe_nombre"),
        titulo=doc_data["titulo"],
        texto_plano=text[:50_000] if text else None,
        hash_texto=hash_text(text) if text else None,
        familia_sancionadora=familia,
        confidence=confidence,
        match_rules=rules,
        url_html=doc_data.get("url_html"),
        url_xml=doc_data.get("url_xml"),
        url_pdf=doc_data.get("url_pdf"),
        raw_sumario_item=doc_data.get("raw_item"),
        source=f"boe_api_{source}",
    )
    db.add(boe_doc)
    db.flush()

    if text:
        result = extract_sanctions(text, titulo=doc_data["titulo"])

        if not result.es_documento_relevante:
            logger.info("OpenAI says %s is not relevant, skipping extraction", boe_id)
            db.commit()
            return

        _save_afectados(db, boe_doc, result.afectados, new_sancionados, stats)

    db.commit()


def _scrape_teu(db, target_date: date, new_sancionados: list, stats: dict) -> dict:
    """Scrape the Tablón Edictal Único for sanction/embargo/debt notifications."""
    teu_stats = {"total": 0, "relevant": 0, "extracted": 0, "errors": 0, "skipped_limit": 0}

    html = fetch_teu_index(target_date)
    all_entries = parse_teu_index(html, target_date)
    teu_stats["total"] = len(all_entries)
    stats["total_docs"] += len(all_entries)

    relevant = filter_relevant_teu_entries(all_entries)
    teu_stats["relevant"] = len(relevant)

    if len(relevant) > MAX_TEU_PER_RUN:
        teu_stats["skipped_limit"] = len(relevant) - MAX_TEU_PER_RUN
        logger.info(
            "TEU: capping %d relevant entries to %d (limit per run)",
            len(relevant), MAX_TEU_PER_RUN,
        )
        relevant = relevant[:MAX_TEU_PER_RUN]

    for entry in relevant:
        try:
            boe_id = entry["identificador"]

            existing = db.execute(
                select(BoeDocumento).where(BoeDocumento.boe_id == boe_id)
            ).scalar_one_or_none()
            if existing:
                continue

            pdf_bytes = fetch_teu_pdf(entry["url_pdf"])
            if not pdf_bytes:
                continue

            text = pdf_to_text(pdf_bytes)
            if not text or len(text) < 50:
                continue

            body_ok, body_signals = verify_with_body(text)

            boe_doc = BoeDocumento(
                boe_id=boe_id,
                fecha_publicacion=entry["fecha_publicacion"],
                seccion_codigo="TEU",
                seccion_nombre="Tablón Edictal Único",
                departamento_nombre=entry.get("departamento_nombre"),
                titulo=entry["titulo"],
                texto_plano=text[:50_000],
                hash_texto=hash_text(text),
                familia_sancionadora="notificacion_teu",
                confidence=0.80,
                match_rules=body_signals if body_ok else ["teu_title_match"],
                url_pdf=entry["url_pdf"],
                source="teu_pdf",
            )
            db.add(boe_doc)
            db.flush()
            stats["candidates"] += 1

            result = extract_sanctions(text, titulo=entry["titulo"])

            if not result.es_documento_relevante:
                logger.debug("TEU %s marked as not relevant by model", boe_id)
                db.commit()
                continue

            before = stats["extracted"]
            _save_afectados(db, boe_doc, result.afectados, new_sancionados, stats)
            teu_stats["extracted"] += stats["extracted"] - before

            db.commit()
            time.sleep(0.2)

        except Exception:
            teu_stats["errors"] += 1
            db.rollback()
            logger.exception("Error processing TEU entry %s", entry.get("identificador"))

    return teu_stats
