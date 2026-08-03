"""Celery wrapper around the contact-enrichment cascade.

Thin by design, same shape as ``app.tasks.scraping``: the Celery task is a
wrapper, the actual logic (``run_enrichment_for``/``run_batch``) is a plain
function so tests can call it directly with a real (ephemeral) database and no
Celery broker involved.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.celery_app import celery
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.services.enrichment.service import EnrichmentDisabled, enrich_sancionado, enrichment_available


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


@celery.task(name="app.tasks.enrichment.enrich_sancionado_task")
def enrich_sancionado_task(sancionado_id: int) -> dict:
    return run_enrichment_for(sancionado_id)


@celery.task(name="app.tasks.enrichment.enrich_batch_task")
def enrich_batch_task(limite: int, fecha_desde: str | None = None, fecha_hasta: str | None = None) -> dict:
    fd = date.fromisoformat(fecha_desde) if fecha_desde else None
    fh = date.fromisoformat(fecha_hasta) if fecha_hasta else None
    return run_batch(limite, fd, fh)
