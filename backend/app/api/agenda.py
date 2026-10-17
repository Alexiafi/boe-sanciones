"""Global agenda: every scheduled action (call, email, task) of every client,
soonest first — what Judit works through each morning."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.cliente import AccionAgendada, Cliente
from app.schemas.cliente import AgendaItemOut

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


def _zona():
    """Judit's day is a Madrid day: "today" must not roll over at 02:00."""
    try:
        return ZoneInfo("Europe/Madrid")
    except ZoneInfoNotFoundError:  # no tz database in this image
        return timezone.utc


@router.get("", response_model=list[AgendaItemOut])
async def listar_agenda(
    estado: str = Query("pendiente", pattern="^(pendiente|hecha|cancelada|todas)$"),
    hasta: date | None = Query(None, description="Solo acciones con fecha hasta este día (inclusive)."),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    consulta = select(AccionAgendada, Cliente.nombre_razon_social, Cliente.codigo).join(
        Cliente, Cliente.id == AccionAgendada.cliente_id
    )
    if estado != "todas":
        consulta = consulta.where(AccionAgendada.estado == estado)
    if hasta is not None:
        fin = datetime.combine(hasta, time.max, tzinfo=_zona())
        consulta = consulta.where(AccionAgendada.fecha_programada.is_not(None), AccionAgendada.fecha_programada <= fin)
    consulta = consulta.order_by(AccionAgendada.fecha_programada.asc().nulls_last(), AccionAgendada.id).limit(limit)

    ahora = datetime.now(timezone.utc)
    items = []
    for accion, nombre, codigo in (await db.execute(consulta)).all():
        item = AgendaItemOut.model_validate(accion)
        item.cliente_nombre = nombre
        item.cliente_codigo = codigo
        item.vencida = bool(
            accion.estado == "pendiente" and accion.fecha_programada is not None and accion.fecha_programada < ahora
        )
        items.append(item)
    return items


@router.get("/resumen", response_model=dict)
async def resumen_agenda(db: AsyncSession = Depends(get_db)):
    """Counters for the home page: overdue, due today, due later, undated."""
    hoy = datetime.now(_zona()).date()
    inicio = datetime.combine(hoy, time.min, tzinfo=_zona())
    fin = datetime.combine(hoy, time.max, tzinfo=_zona())
    pendientes = AccionAgendada.estado == "pendiente"

    async def contar(*condiciones) -> int:
        return int((await db.execute(select(func.count(AccionAgendada.id)).where(pendientes, *condiciones))).scalar_one())

    return {
        "vencidas": await contar(AccionAgendada.fecha_programada.is_not(None), AccionAgendada.fecha_programada < inicio),
        "hoy": await contar(AccionAgendada.fecha_programada >= inicio, AccionAgendada.fecha_programada <= fin),
        "proximas": await contar(AccionAgendada.fecha_programada > fin),
        "sin_fecha": await contar(AccionAgendada.fecha_programada.is_(None)),
    }
