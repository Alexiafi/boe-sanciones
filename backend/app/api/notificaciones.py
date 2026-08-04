"""API endpoints for notifications."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.notificacion import Notificacion
from app.schemas.sancionado import NotificacionMarkRead, NotificacionOut

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


@router.get("", response_model=dict)
async def list_notificaciones(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    solo_no_leidas: bool = False,
    solo_clientes: bool = False,
    db: AsyncSession = Depends(get_db),
):
    query = select(Notificacion).order_by(Notificacion.created_at.desc())
    count_query = select(func.count(Notificacion.id))

    if solo_no_leidas:
        query = query.where(Notificacion.leida == False)  # noqa: E712
        count_query = count_query.where(Notificacion.leida == False)  # noqa: E712
    if solo_clientes:
        query = query.where(Notificacion.cliente_id.is_not(None))
        count_query = count_query.where(Notificacion.cliente_id.is_not(None))

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    results = (await db.execute(query.offset(offset).limit(page_size))).scalars().all()

    return {
        "items": [NotificacionOut.model_validate(n).model_dump() for n in results],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/unread-count", response_model=dict)
async def unread_count(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(func.count(Notificacion.id)).where(Notificacion.leida == False)  # noqa: E712
    )
    result_clientes = await db.execute(
        select(func.count(Notificacion.id)).where(
            Notificacion.leida == False, Notificacion.cliente_id.is_not(None)  # noqa: E712
        )
    )
    return {"count": result.scalar() or 0, "count_clientes": result_clientes.scalar() or 0}


@router.post("/mark-read", response_model=dict)
async def mark_as_read(data: NotificacionMarkRead, db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(Notificacion)
        .where(Notificacion.id.in_(data.ids))
        .values(leida=True)
    )
    await db.commit()
    return {"marked": len(data.ids)}


@router.post("/mark-all-read", response_model=dict)
async def mark_all_read(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        update(Notificacion)
        .where(Notificacion.leida == False)  # noqa: E712
        .values(leida=True)
    )
    await db.commit()
    return {"marked": result.rowcount}
