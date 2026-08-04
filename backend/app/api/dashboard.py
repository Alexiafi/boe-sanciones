"""Dashboard stats endpoint."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.documento import BoeDocumento
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.models.scraping_run import ScrapingRun

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=dict)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    today = date.today()
    week_ago = today - timedelta(days=7)

    total_docs = (await db.execute(select(func.count(BoeDocumento.id)))).scalar() or 0
    total_sancionados = (await db.execute(select(func.count(Sancionado.id)))).scalar() or 0
    docs_today = (await db.execute(
        select(func.count(BoeDocumento.id)).where(BoeDocumento.fecha_publicacion == today)
    )).scalar() or 0
    sancionados_today = (await db.execute(
        select(func.count(Sancionado.id))
        .join(BoeDocumento)
        .where(BoeDocumento.fecha_publicacion == today)
    )).scalar() or 0
    sancionados_week = (await db.execute(
        select(func.count(Sancionado.id))
        .join(BoeDocumento)
        .where(BoeDocumento.fecha_publicacion >= week_ago)
    )).scalar() or 0
    unread_notifs = (await db.execute(
        select(func.count(Notificacion.id)).where(Notificacion.leida == False)  # noqa: E712
    )).scalar() or 0
    unread_client_alerts = (await db.execute(
        select(func.count(Notificacion.id)).where(
            Notificacion.leida == False, Notificacion.cliente_id.is_not(None)  # noqa: E712
        )
    )).scalar() or 0

    last_run = (await db.execute(
        select(ScrapingRun).order_by(ScrapingRun.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    top_organismos = (await db.execute(
        select(
            Sancionado.organismo_emisor,
            func.count(Sancionado.id).label("total"),
        )
        .where(Sancionado.organismo_emisor.isnot(None))
        .group_by(Sancionado.organismo_emisor)
        .order_by(func.count(Sancionado.id).desc())
        .limit(5)
    )).all()

    infraccion_counts = (await db.execute(
        select(
            Sancionado.tipo_infraccion,
            func.count(Sancionado.id).label("total"),
        )
        .where(Sancionado.tipo_infraccion.isnot(None))
        .group_by(Sancionado.tipo_infraccion)
    )).all()

    return {
        "total_documentos": total_docs,
        "total_sancionados": total_sancionados,
        "documentos_hoy": docs_today,
        "sancionados_hoy": sancionados_today,
        "sancionados_semana": sancionados_week,
        "notificaciones_sin_leer": unread_notifs,
        "alertas_clientes_sin_leer": unread_client_alerts,
        "ultimo_scraping": {
            "fecha": str(last_run.fecha_boe) if last_run else None,
            "status": last_run.status if last_run else None,
            "extracted": last_run.extracted if last_run else None,
            "finished_at": str(last_run.finished_at) if last_run and last_run.finished_at else None,
        },
        "top_organismos": [
            {"nombre": row[0], "total": row[1]} for row in top_organismos
        ],
        "infracciones_por_tipo": [
            {"tipo": row[0], "total": row[1]} for row in infraccion_counts
        ],
    }
