"""API endpoints for scraping management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.scraping_run import ScrapingRun
from app.schemas.sancionado import ScrapingRunOut, ScrapingTrigger
from app.tasks.scraping import run_daily_scraping

router = APIRouter(prefix="/api/scraping", tags=["scraping"])


@router.post("/trigger", response_model=dict)
async def trigger_scraping(data: ScrapingTrigger):
    force = getattr(data, "force", False)
    task = run_daily_scraping.delay(data.fecha, force=force)
    return {"task_id": task.id, "status": "queued", "fecha": data.fecha}


@router.get("/runs", response_model=list[ScrapingRunOut])
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScrapingRun).order_by(ScrapingRun.created_at.desc()).limit(limit)
    )
    return [ScrapingRunOut.model_validate(r) for r in result.scalars().all()]


@router.get("/status/{task_id}", response_model=dict)
async def task_status(task_id: str):
    result = run_daily_scraping.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }
