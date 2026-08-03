"""Batch contact enrichment — off by default, with an explicit confirmation gate
on top of the ``ENRICHMENT_BATCH_ENABLED`` config flag. Mirrors the manual
scraping trigger's double-gate pattern from session 1.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.sancionado import EnriquecimientoLoteRequest
from app.services.enrichment.service import enrichment_available
from app.tasks.enrichment import enrich_batch_task

router = APIRouter(prefix="/api/enriquecimiento", tags=["enriquecimiento"])


@router.post("/lote", response_model=dict)
async def enrich_lote(data: EnriquecimientoLoteRequest):
    if not data.confirmar:
        raise HTTPException(status_code=422, detail="Debe confirmar explícitamente el lote (confirmar=true).")
    if not settings.enrichment_batch_enabled:
        raise HTTPException(status_code=409, detail="El enriquecimiento en lote está desactivado (ENRICHMENT_BATCH_ENABLED=false).")
    available, reason = enrichment_available()
    if not available:
        raise HTTPException(status_code=409, detail=reason)
    limite = min(data.limite, settings.enrichment_batch_max) if data.limite else settings.enrichment_batch_max
    task = enrich_batch_task.delay(
        limite,
        data.fecha_desde.isoformat() if data.fecha_desde else None,
        data.fecha_hasta.isoformat() if data.fecha_hasta else None,
    )
    return {"task_id": task.id, "status": "queued", "limite": limite}


@router.get("/status/{task_id}", response_model=dict)
async def batch_status(task_id: str):
    result = enrich_batch_task.AsyncResult(task_id)
    return {"task_id": task_id, "status": result.status, "result": result.result if result.ready() else None}
