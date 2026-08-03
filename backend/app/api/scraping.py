"""API endpoints for scraping management."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.scraping_run import ScrapingRun
from app.schemas.sancionado import ScrapingRunOut, ScrapingTrigger
from app.tasks.scraping import run_daily_scraping

router = APIRouter(prefix="/api/scraping", tags=["scraping"])


@router.post("/trigger", response_model=dict)
async def trigger_scraping(data: ScrapingTrigger):
    try:
        target = date.fromisoformat(data.fecha)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="fecha debe usar YYYY-MM-DD") from exc
    if data.permitir_extraccion_pago and (not settings.openai_extraction_enabled or not settings.openai_api_key):
        raise HTTPException(
            status_code=409,
            detail="La extracción OpenAI está deshabilitada; active configuración y API key antes de confirmarla.",
        )
    task = run_daily_scraping.delay(target.isoformat(), force=data.force, permitir_extraccion_pago=data.permitir_extraccion_pago)
    return {
        "task_id": task.id,
        "status": "queued",
        "fecha": target.isoformat(),
        "extraccion_pago": data.permitir_extraccion_pago,
        "limite_documentos": settings.openai_extraction_max_documents_per_run if data.permitir_extraccion_pago else 0,
    }


@router.get("/runs", response_model=list[ScrapingRunOut])
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScrapingRun).order_by(ScrapingRun.created_at.desc()).limit(limit)
    )
    return [ScrapingRunOut.model_validate(r) for r in result.scalars().all()]


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
        "note": "Fechas sin ejecución completada; no confirma que el BOE publicase ese día.",
    }


@router.get("/status/{task_id}", response_model=dict)
async def task_status(task_id: str):
    result = run_daily_scraping.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
