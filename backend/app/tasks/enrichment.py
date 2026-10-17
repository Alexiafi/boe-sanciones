"""Celery wrapper around the contact-enrichment cascade.

Thin by design, same shape as ``app.tasks.scraping``: the Celery task is a
wrapper, the actual logic (``run_enrichment_for``/``run_batch``) is a plain
function so tests can call it directly with a real (ephemeral) database and no
Celery broker involved.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.celery_app import celery
from app.database import SyncSessionLocal, sync_engine
from app.models.documento import BoeDocumento
from app.models.enriquecimiento import EnriquecimientoIntento
from app.models.sancionado import Sancionado
from app.services.configuracion import leer_configuracion
from app.services.enrichment.service import EnrichmentDisabled, enrich_sancionado, enrichment_available

logger = logging.getLogger(__name__)

# Automatic enrichment of new company notices (see run_enriquecimiento_automatico).
AUTO_LOTE = 40          # companies per run (a run every 15 min)
AUTO_DIAS = 7           # only notices that arrived in the last week
_MADRID = ZoneInfo("Europe/Madrid")


def run_enrichment_for(sancionado_id: int) -> dict:
    available, reason = enrichment_available()
    if not available:
        raise EnrichmentDisabled(reason)
    db = SyncSessionLocal()
    try:
        sancionado = db.get(Sancionado, sancionado_id)
        if sancionado is None:
            raise ValueError(f"Sancionado {sancionado_id} no encontrado")
        result = enrich_sancionado(db, sancionado)
        db.commit()
        return {
            "sancionado_id": sancionado_id,
            "estado": result.estado,
            "fuente": result.fuente,
            "confidence": result.confidence,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_batch(limite: int, fecha_desde: date | None = None, fecha_hasta: date | None = None) -> dict:
    """Enrich up to ``limite`` pending opportunities. Caller (API layer) is
    responsible for enforcing ``ENRICHMENT_BATCH_ENABLED`` and the explicit
    ``confirmar=true`` gate before this runs."""
    available, reason = enrichment_available()
    if not available:
        raise EnrichmentDisabled(reason)
    db = SyncSessionLocal()
    processed: list[dict] = []
    try:
        query = select(Sancionado).where(Sancionado.contacto_estado == "pendiente")
        if fecha_desde or fecha_hasta:
            query = query.join(Sancionado.documento)
            if fecha_desde:
                query = query.where(BoeDocumento.fecha_publicacion >= fecha_desde)
            if fecha_hasta:
                query = query.where(BoeDocumento.fecha_publicacion <= fecha_hasta)
        query = query.order_by(Sancionado.id).limit(limite)
        candidates = db.execute(query).scalars().all()
        for sancionado in candidates:
            result = enrich_sancionado(db, sancionado)
            processed.append({"sancionado_id": sancionado.id, "estado": result.estado})
            db.commit()
        return {"total": len(processed), "items": processed}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def intentos_de_hoy(db) -> int:
    inicio = datetime.now(_MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(db.execute(
        select(func.count(EnriquecimientoIntento.id)).where(EnriquecimientoIntento.created_at >= inicio)
    ).scalar() or 0)


def run_enriquecimiento_automatico(lote: int = AUTO_LOTE) -> dict:
    """Search the web for the razón social and contact of new COMPANY notices
    (complete CIF, still "pendiente", arrived in the last ``AUTO_DIAS`` days),
    newest first, within the daily ceiling of the runtime configuration.

    Off unless the operator turned ``enriquecimiento_automatico`` on in
    "Configuración" (on top of the ``.env`` gate): each company costs one or two
    paid searches. A party's other notices are answered for free afterwards —
    from what was found (``compartir_perfil``) or from the query cache. People
    (DNI/NIE) are never searched automatically."""
    available, reason = enrichment_available()
    if not available:
        return {"skipped": True, "reason": reason}
    db = SyncSessionLocal()
    lock = sync_engine.connect()
    bloqueado = False
    procesados: list[dict] = []
    try:
        config = leer_configuracion(db)
        if not config.enriquecimiento_automatico:
            return {"skipped": True, "reason": "enriquecimiento_automatico desactivado"}
        bloqueado = bool(lock.execute(text("SELECT pg_try_advisory_lock(hashtext('enriquecimiento-auto'))")).scalar())
        if not bloqueado:
            return {"skipped": True, "reason": "already_running"}
        restantes = config.enriquecimiento_max_por_dia - intentos_de_hoy(db)
        if restantes <= 0:
            return {"skipped": True, "reason": "tope_diario"}
        desde = datetime.now(timezone.utc) - timedelta(days=AUTO_DIAS)
        candidatos = db.execute(
            select(Sancionado).where(
                Sancionado.contacto_estado == "pendiente",
                Sancionado.created_at >= desde,
                # A complete CIF (company); DNI/NIE start with a digit or X/Y/Z.
                Sancionado.identidad_clave.op("~")("^[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-J]$"),
            ).order_by(Sancionado.id.desc()).limit(min(lote, restantes))
        ).scalars().all()
        for sancionado in candidatos:
            db.refresh(sancionado)
            if sancionado.contacto_estado != "pendiente":
                continue  # answered meanwhile by a sibling of the same CIF
            try:
                result = enrich_sancionado(db, sancionado)
                db.commit()
                procesados.append({"sancionado_id": sancionado.id, "estado": result.estado})
            except EnrichmentDisabled:
                db.rollback()
                break
            except Exception:
                db.rollback()
                logger.exception("Enriquecimiento automático fallido para %s", sancionado.id)
        return {"total": len(procesados), "items": procesados}
    finally:
        if bloqueado:
            try:
                lock.execute(text("SELECT pg_advisory_unlock(hashtext('enriquecimiento-auto'))"))
                lock.commit()
            except Exception:
                pass
        lock.close()
        db.close()


@celery.task(name="app.tasks.enrichment.enriquecimiento_automatico_task")
def enriquecimiento_automatico_task() -> dict:
    return run_enriquecimiento_automatico()


@celery.task(name="app.tasks.enrichment.enrich_sancionado_task")
def enrich_sancionado_task(sancionado_id: int) -> dict:
    return run_enrichment_for(sancionado_id)


@celery.task(name="app.tasks.enrichment.enrich_batch_task")
def enrich_batch_task(limite: int, fecha_desde: str | None = None, fecha_hasta: str | None = None) -> dict:
    fd = date.fromisoformat(fecha_desde) if fecha_desde else None
    fh = date.fromisoformat(fecha_hasta) if fecha_hasta else None
    return run_batch(limite, fd, fh)
