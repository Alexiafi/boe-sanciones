"""API endpoints for notifications."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.cliente import Cliente
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.schemas.sancionado import NotificacionMarkRead, NotificacionOut

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


def _es_de_cliente():
    """A notification "belongs to a client" when it was raised for one
    (``cliente_id``, radar/auto-assignment) OR when the sanction it announced
    has since been attached to a client (conversion, manual assignment). The
    second half is what makes "Solo mis clientes" show the sanctions Judit
    converted herself, not only the ones the pipeline matched later."""
    return or_(Notificacion.cliente_id.is_not(None), Sancionado.cliente_id.is_not(None))


def _cliente_efectivo():
    return func.coalesce(Notificacion.cliente_id, Sancionado.cliente_id)


@router.get("", response_model=dict)
async def list_notificaciones(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    solo_no_leidas: bool = False,
    solo_clientes: bool = False,
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if solo_no_leidas:
        conditions.append(Notificacion.leida == False)  # noqa: E712
    if solo_clientes:
        conditions.append(_es_de_cliente())

    base = (
        select(
            Notificacion, _cliente_efectivo().label("cliente_efectivo_id"), Cliente.nombre_razon_social,
            Sancionado.nombre, Sancionado.identificador,
        )
        .outerjoin(Sancionado, Sancionado.id == Notificacion.sancionado_id)
        .outerjoin(Cliente, Cliente.id == _cliente_efectivo())
        .where(*conditions)
        .order_by(Notificacion.created_at.desc())
    )
    count_query = (
        select(func.count(Notificacion.id))
        .outerjoin(Sancionado, Sancionado.id == Notificacion.sancionado_id)
        .where(*conditions)
    )

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    rows = (await db.execute(base.offset(offset).limit(page_size))).all()

    items = []
    for notificacion, cliente_efectivo_id, cliente_nombre, nombre, identificador in rows:
        item = NotificacionOut.model_validate(notificacion).model_dump()
        item["cliente_id"] = cliente_efectivo_id
        item["cliente_nombre"] = cliente_nombre
        item["identificador"] = identificador
        # Alerts raised before the party was known (or before it became a
        # client) were stored as "Nueva sanción: Desconocido"; the title is
        # rebuilt from what is known now.
        if notificacion.tipo in ("nueva_sancion", "nueva_sancion_cliente") and notificacion.sancionado_id:
            if cliente_efectivo_id and cliente_nombre:
                item["titulo"] = f"Nueva sanción de cliente: {cliente_nombre}"
            elif nombre or identificador:
                item["titulo"] = f"Nueva sanción: {nombre or identificador}"
        items.append(item)

    return {
        "items": items,
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
        select(func.count(Notificacion.id))
        .outerjoin(Sancionado, Sancionado.id == Notificacion.sancionado_id)
        .where(Notificacion.leida == False, _es_de_cliente())  # noqa: E712
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
