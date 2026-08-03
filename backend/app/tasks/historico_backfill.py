"""Manual-only, resumable, bounded historical backfill.

This module must never import ``app.services.extractor`` — not even to leave
it unused. Backfill indexing is regex-only
(``app/services/historico/patterns.py``); the structural absence of an
extractor import here is itself the guarantee — not just a runtime flag —
that no code path in this file can call OpenAI.
``tests/test_historico_backfill.py`` asserts this structurally.

Never registered in ``celery.conf.beat_schedule`` (see ``app/celery_app.py``):
this task runs only when a human explicitly requests it through
``POST /api/historico/backfill``, and only after a two-step
plan -> confirm handshake (see ``plan_backfill``/``token_confirmacion``) that
echoes back the exact range, day/document limits and estimated volume.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select, text

from app.celery_app import celery
from app.config import settings
from app.database import SyncSessionLocal, sync_engine
from app.models.historico import HistoricoBackfillRun
from app.services.boe_client import fetch_document_content, fetch_document_pdf, fetch_sumario, flatten_sumario
from app.services.classifier import classify_document, should_skip_section, verify_with_body
from app.services.historico.indexado import upsert_from_doc_data
from app.services.parser import extract_text_from_document

logger = logging.getLogger(__name__)

# Rough, documented constants used only to preview volume before anything
# runs (see plan_backfill). Never used to decide behaviour.
DOCS_ESTIMADOS_POR_DIA = 350
CANDIDATOS_ESTIMADOS_POR_DIA = 40


class BackfillNoPermitido(ValueError):
    """Raised when a backfill is requested without every gate open."""


@dataclass(frozen=True)
class BackfillDependencies:
    fetch_sumario: Callable[[date], dict] = fetch_sumario
    flatten_sumario: Callable[[dict, date], list[dict[str, Any]]] = flatten_sumario
    fetch_text: Callable[[dict[str, Any]], tuple[str, str]] | None = None
    sleep: Callable[[float], None] = time.sleep


def _fetch_text_default(doc_data: dict[str, Any]) -> tuple[str, str]:
    return extract_text_from_document(
        doc_data.get("url_xml"), doc_data.get("url_html"), doc_data.get("url_pdf"),
        fetch_fn=fetch_document_content, fetch_pdf_fn=fetch_document_pdf,
    )


def _get_text(deps: BackfillDependencies, doc_data: dict[str, Any]) -> tuple[str, str]:
    return (deps.fetch_text or _fetch_text_default)(doc_data)


def token_confirmacion(desde: date, hasta: date, max_dias: int, max_docs: int) -> str:
    """Hash of range AND limits — not just the dates — so a confirmation for
    one range/limit pair can never be replayed against a wider one."""
    dias = (hasta - desde).days + 1
    payload = f"backfill:{desde.isoformat()}:{hasta.isoformat()}:{dias}:{max_dias}:{max_docs}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def backfill_available() -> tuple[bool, str | None]:
    if not settings.historico_backfill_enabled:
        return False, "El backfill histórico está desactivado (HISTORICO_BACKFILL_ENABLED=false)."
    return True, None


def plan_backfill(fecha_desde: date, fecha_hasta: date) -> dict[str, Any]:
    """Pure arithmetic preview: no network access, no database writes."""
    dias = (fecha_hasta - fecha_desde).days + 1
    max_dias = settings.historico_backfill_max_dias_por_lote
    max_docs = settings.historico_backfill_max_docs_por_lote
    documentos_estimados = dias * DOCS_ESTIMADOS_POR_DIA
    candidatos_estimados = dias * CANDIDATOS_ESTIMADOS_POR_DIA
    ejecuciones_estimadas = max(1, -(-dias // max_dias))  # ceil division
    return {
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "dias": dias,
        "documentos_estimados": documentos_estimados,
        "candidatos_estimados": candidatos_estimados,
        "max_dias_por_ejecucion": max_dias,
        "max_documentos_por_ejecucion": max_docs,
        "ejecuciones_estimadas": ejecuciones_estimadas,
        "token": token_confirmacion(fecha_desde, fecha_hasta, max_dias, max_docs),
        "aviso": (
            f"Se descargarán hasta {documentos_estimados} documentos desde boe.es a lo largo de "
            f"~{ejecuciones_estimadas} ejecuciones manuales (máx. {max_dias} días / {max_docs} documentos "
            "cada una). Sin OpenAI y sin coste monetario; sí consume tiempo y ancho de banda de boe.es."
        ),
    }


def _try_acquire_lock(connection) -> bool:
    return bool(connection.execute(text("SELECT pg_try_advisory_lock(hashtext('historico-backfill'))")).scalar())


def _release_lock(connection) -> None:
    connection.execute(text("SELECT pg_advisory_unlock(hashtext('historico-backfill'))"))


def run_backfill(
    fecha_desde: str | date,
    fecha_hasta: str | date,
    *,
    confirmacion: str,
    max_dias: int | None = None,
    max_documentos: int | None = None,
    dependencies: BackfillDependencies | None = None,
) -> dict[str, Any]:
    desde = fecha_desde if isinstance(fecha_desde, date) else date.fromisoformat(fecha_desde)
    hasta = fecha_hasta if isinstance(fecha_hasta, date) else date.fromisoformat(fecha_hasta)
    if desde > hasta:
        raise BackfillNoPermitido("fecha_desde no puede ser posterior a fecha_hasta.")

    disponible, motivo = backfill_available()
    if not disponible:
        raise BackfillNoPermitido(motivo)

    # A caller may only ask for LESS than the configured ceiling, never more.
    limite_dias = min(max_dias, settings.historico_backfill_max_dias_por_lote) if max_dias else settings.historico_backfill_max_dias_por_lote
    limite_docs = min(max_documentos, settings.historico_backfill_max_docs_por_lote) if max_documentos else settings.historico_backfill_max_docs_por_lote

    esperado = token_confirmacion(
        desde, hasta, settings.historico_backfill_max_dias_por_lote, settings.historico_backfill_max_docs_por_lote
    )
    if confirmacion != esperado:
        raise BackfillNoPermitido(
            "El token de confirmación no coincide con el rango y los límites configurados. "
            "Solicite un nuevo plan (POST /api/historico/backfill/plan) y confirme exactamente ese rango."
        )

    deps = dependencies or BackfillDependencies()
    db = SyncSessionLocal()
    lock_connection = sync_engine.connect()
    lock_acquired = False
    try:
        # Dedicated connection for the advisory lock, same reason as
        # tasks/scraping.py: the work session commits per day and must not
        # own the lock connection.
        lock_acquired = _try_acquire_lock(lock_connection)
        if not lock_acquired:
            return {"skipped": True, "reason": "already_running"}

        run = db.execute(
            select(HistoricoBackfillRun).where(
                HistoricoBackfillRun.fecha_desde == desde, HistoricoBackfillRun.fecha_hasta == hasta,
            )
        ).scalar_one_or_none()
        if run is None:
            run = HistoricoBackfillRun(
                fecha_desde=desde, fecha_hasta=hasta, cursor_fecha=hasta,
                dias_totales=(hasta - desde).days + 1, status="en_curso",
                confirmacion_token=confirmacion, started_at=datetime.now(timezone.utc),
            )
            db.add(run)
            db.flush()
        elif run.status == "completado":
            return {"skipped": True, "reason": "already_completed", "run_id": run.id}
        else:
            run.status = "en_curso"
            if run.started_at is None:
                run.started_at = datetime.now(timezone.utc)
        db.commit()

        cursor = run.cursor_fecha or hasta
        dias_esta_ejecucion = 0
        docs_esta_ejecucion = 0

        # Walks BACKWARDS from fecha_hasta: newest history first, which is
        # the part most likely to matter for a freshly converted client.
        while cursor >= desde and dias_esta_ejecucion < limite_dias and docs_esta_ejecucion < limite_docs:
            try:
                payload = deps.fetch_sumario(cursor)
                docs = deps.flatten_sumario(payload, cursor)
            except Exception:
                logger.exception("No se pudo obtener el sumario del %s; se cuenta como procesado", cursor)
                run.errores += 1
                docs = []

            for doc_data in docs:
                if docs_esta_ejecucion >= limite_docs:
                    break
                run.docs_vistos += 1
                if not doc_data.get("identificador") or should_skip_section(doc_data):
                    continue
                candidato, _rules, confidence, familia = classify_document(doc_data)
                if not candidato:
                    continue
                run.docs_candidatos += 1
                texto, _fuente = _get_text(deps, doc_data)
                if texto:
                    body_ok, _signals = verify_with_body(texto)
                    if not body_ok:
                        continue
                resultado = upsert_from_doc_data(
                    db, doc_data, texto, fuente="boe", origen_indexado="backfill",
                    familia_sancionadora=familia, confidence=confidence,
                    guardar_texto=settings.historico_backfill_store_text,
                )
                if resultado is not None and resultado[1]:  # (doc, creado)
                    run.docs_indexados += 1
                    docs_esta_ejecucion += 1

            dias_esta_ejecucion += 1
            run.dias_procesados += 1
            run.ultima_fecha_completada = cursor
            cursor -= timedelta(days=1)
            # The cursor advances in the SAME transaction as this day's
            # historico_docs rows: an interruption rolls back both together,
            # so resume never re-does more than the in-flight day.
            run.cursor_fecha = cursor
            db.commit()
            deps.sleep(settings.historico_backfill_delay_s)

        run.status = "completado" if cursor < desde else "pausado"
        run.finished_at = datetime.now(timezone.utc) if run.status == "completado" else None
        db.commit()

        return {
            "run_id": run.id,
            "status": run.status,
            "dias_procesados_total": run.dias_procesados,
            "docs_indexados_total": run.docs_indexados,
            "dias_procesados_esta_ejecucion": dias_esta_ejecucion,
            "docs_indexados_esta_ejecucion": docs_esta_ejecucion,
            "cursor_fecha": run.cursor_fecha.isoformat() if run.cursor_fecha else None,
            "reanudable": run.status == "pausado",
        }
    except Exception:
        db.rollback()
        logger.exception("Backfill histórico interrumpido por un error (%s a %s)", desde, hasta)
        raise
    finally:
        if lock_acquired:
            try:
                _release_lock(lock_connection)
                lock_connection.commit()
            except Exception:
                pass
        lock_connection.close()
        db.close()


@celery.task(name="app.tasks.historico_backfill.run_backfill_task")
def run_backfill_task(
    fecha_desde: str, fecha_hasta: str, confirmacion: str,
    max_dias: int | None = None, max_documentos: int | None = None,
) -> dict:
    return run_backfill(
        fecha_desde, fecha_hasta, confirmacion=confirmacion, max_dias=max_dias, max_documentos=max_documentos
    )
