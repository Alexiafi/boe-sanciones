"""API endpoints for scraping management."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import SyncSessionLocal, get_db
from app.models.extraccion_batch import ExtraccionBatch
from app.models.scraping_run import ScrapingRun
from app.schemas.sancionado import ExtraccionBatchItemOut, ExtraccionBatchOut, ScrapingRunOut, ScrapingTrigger
from app.services.configuracion import extraccion_disponible, leer_configuracion_async
from app.tasks.extraccion_batch import procesar_batches_pendientes_task
from app.tasks.scraping import catch_up_scraping, fechas_pendientes, marcar_runs_colgados, run_daily_scraping

router = APIRouter(prefix="/api/scraping", tags=["scraping"])


@router.post("/trigger", response_model=dict)
async def trigger_scraping(data: ScrapingTrigger, db: AsyncSession = Depends(get_db)):
    try:
        target = date.fromisoformat(data.fecha)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="fecha debe usar YYYY-MM-DD") from exc
    if data.permitir_extraccion_pago and not extraccion_disponible()[0]:
        raise HTTPException(
            status_code=409,
            detail="La extracción OpenAI está deshabilitada; active configuración y API key antes de confirmarla.",
        )
    config = await leer_configuracion_async(db)
    modo = data.modo_extraccion or config.extraccion_modo
    task = run_daily_scraping.delay(
        target.isoformat(), force=data.force, permitir_extraccion_pago=data.permitir_extraccion_pago,
        modo_extraccion=modo,
    )
    return {
        "task_id": task.id,
        "status": "queued",
        "fecha": target.isoformat(),
        "extraccion_pago": data.permitir_extraccion_pago,
        "modo_extraccion": modo if data.permitir_extraccion_pago else None,
        "limite_documentos": config.extraccion_max_docs_por_ejecucion if data.permitir_extraccion_pago else 0,
    }


@router.post("/catch-up", response_model=dict)
async def trigger_catch_up():
    """Queue a run for every recent date without a completed run (same task
    Celery beat runs three times a day and the worker runs at start-up)."""
    task = catch_up_scraping.delay()
    return {"task_id": task.id, "status": "queued"}


@router.get("/runs", response_model=list[ScrapingRunOut])
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    # Runs abandoned by a dead worker must not linger as "running" in the
    # UI; the check is a single indexed query.
    await run_in_threadpool(_marcar_colgados)
    result = await db.execute(
        select(ScrapingRun).order_by(ScrapingRun.created_at.desc()).limit(limit)
    )
    return [ScrapingRunOut.model_validate(r) for r in result.scalars().all()]


def _marcar_colgados() -> int:
    sync_db = SyncSessionLocal()
    try:
        return marcar_runs_colgados(sync_db)
    finally:
        sync_db.close()


@router.get("/gaps", response_model=dict)
async def detect_gaps(
    days: int = Query(30, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """Return dates with no completed run; this endpoint never queues work."""
    if days > settings.gap_detection_max_days:
        raise HTTPException(status_code=422, detail=f"days no puede superar {settings.gap_detection_max_days}")
    end = date.today()
    start = end - timedelta(days=days - 1)
    result = await db.execute(
        select(ScrapingRun.fecha_boe)
        .where(
            ScrapingRun.fecha_boe >= start,
            ScrapingRun.fecha_boe <= end,
            ScrapingRun.status == "completed",
            ScrapingRun.tipo == "diario",
        )
        .distinct()
    )
    completed = set(result.scalars().all())
    gaps = [start + timedelta(days=offset) for offset in range(days) if start + timedelta(days=offset) not in completed]
    return {
        "desde": start.isoformat(),
        "hasta": end.isoformat(),
        "days": days,
        "gaps": [item.isoformat() for item in gaps],
        "pendientes_catch_up": [item.isoformat() for item in await run_in_threadpool(_pendientes)],
        "note": "Fechas sin ejecución completada; no confirma que el BOE publicase ese día.",
    }


def _pendientes() -> list[date]:
    sync_db = SyncSessionLocal()
    try:
        return fechas_pendientes(sync_db)
    finally:
        sync_db.close()


@router.get("/status/{task_id}", response_model=dict)
async def task_status(task_id: str):
    result = run_daily_scraping.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


@router.get("/batches", response_model=list[ExtraccionBatchOut])
async def list_batches(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExtraccionBatch).order_by(ExtraccionBatch.id.desc()).limit(limit))
    return [ExtraccionBatchOut.model_validate(b) for b in result.scalars().all()]


@router.get("/batches/{batch_id}", response_model=dict)
async def get_batch(batch_id: int, db: AsyncSession = Depends(get_db)):
    batch = (
        await db.execute(
            select(ExtraccionBatch).options(selectinload(ExtraccionBatch.items)).where(ExtraccionBatch.id == batch_id)
        )
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch no encontrado")
    return {
        **ExtraccionBatchOut.model_validate(batch).model_dump(),
        "items": [ExtraccionBatchItemOut.model_validate(item).model_dump() for item in batch.items],
    }


@router.post("/batches/comprobar", response_model=dict)
async def comprobar_batches():
    """Poll OpenAI now instead of waiting for the next scheduled pass."""
    task = procesar_batches_pendientes_task.delay()
    return {"task_id": task.id, "status": "queued"}
