"""API endpoints for operational opportunities."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.models.seguimiento import Seguimiento
from app.schemas.sancionado import SancionadoDetail, SancionadoOut, SancionadoUpdate, SeguimientoCreate, SeguimientoOut

BOE_BASE = "https://www.boe.es"
router = APIRouter(prefix="/api/sanciones", tags=["sanciones"])


def _build_url_documento(doc: BoeDocumento) -> str:
    if doc.url_html:
        return doc.url_html if doc.url_html.startswith("http") else f"{BOE_BASE}{doc.url_html}"
    if doc.url_pdf:
        return doc.url_pdf if doc.url_pdf.startswith("http") else f"{BOE_BASE}{doc.url_pdf}"
    if doc.boe_id.startswith("BOE-N-"):
        return f"{BOE_BASE}/boe_n/dias/{doc.fecha_publicacion.year}/{doc.fecha_publicacion.month:02d}/{doc.fecha_publicacion.day:02d}/not.php?id={doc.boe_id}"
    return f"{BOE_BASE}/diario_boe/txt.php?id={doc.boe_id}"


def _serialise(sancionado: Sancionado) -> SancionadoOut:
    item = SancionadoOut.model_validate(sancionado)
    doc = sancionado.documento
    item.boe_id = doc.boe_id
    item.fecha_publicacion = str(doc.fecha_publicacion)
    item.titulo_documento = doc.titulo
    item.url_html = doc.url_html
    item.url_documento = _build_url_documento(doc)
    return item


@router.get("", response_model=dict)
async def list_sanciones(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    organismo: str | None = None,
    tipo_infraccion: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    estado_oportunidad: str | None = Query(None, pattern="^(nueva|revisada|contactada|descartada|cliente)$"),
    materia: str | None = None,
    tipo_persona: str | None = Query(None, pattern="^(fisica|juridica)$"),
    cuantia_min: Decimal | None = Query(None, ge=0),
    cuantia_max: Decimal | None = Query(None, ge=0),
    solo_con_contacto: bool | None = None,
    estado: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if cuantia_min is not None and cuantia_max is not None and cuantia_min > cuantia_max:
        raise HTTPException(status_code=422, detail="cuantia_min no puede superar cuantia_max")
    if fecha_desde is None and fecha_hasta is None:
        fecha_hasta = date.today()
        fecha_desde = fecha_hasta - timedelta(days=29)

    conditions = []
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Sancionado.codigo.ilike(pattern), Sancionado.nombre.ilike(pattern), Sancionado.identificador.ilike(pattern), Sancionado.expediente.ilike(pattern)))
    if organismo:
        conditions.append(Sancionado.organismo_emisor.ilike(f"%{organismo.strip()}%"))
    if tipo_infraccion:
        conditions.append(Sancionado.tipo_infraccion == tipo_infraccion)
    if fecha_desde:
        conditions.append(BoeDocumento.fecha_publicacion >= fecha_desde)
    if fecha_hasta:
        conditions.append(BoeDocumento.fecha_publicacion <= fecha_hasta)
    if estado_oportunidad:
        conditions.append(Sancionado.estado_oportunidad == estado_oportunidad)
    if materia:
        conditions.append(Sancionado.dominio_material.ilike(f"%{materia.strip()}%"))
    if tipo_persona:
        conditions.append(Sancionado.tipo_persona == tipo_persona)
    amount = func.coalesce(Sancionado.importe_multa_eur, Sancionado.importe_deuda_eur)
    if cuantia_min is not None:
        conditions.append(amount >= cuantia_min)
    if cuantia_max is not None:
        conditions.append(amount <= cuantia_max)
    has_contact = or_(func.nullif(func.trim(Sancionado.telefono), "").isnot(None), func.nullif(func.trim(Sancionado.email), "").isnot(None))
    if solo_con_contacto is True:
        conditions.append(has_contact)
    elif solo_con_contacto is False:
        conditions.append(~has_contact)
    # Compatibility with the pre-session endpoint: this remains a historial
    # filter and does not replace the opportunity state.
    if estado:
        conditions.append(Sancionado.id.in_(select(Seguimiento.sancionado_id).where(Seguimiento.estado == estado).distinct()))

    statement = (
        select(Sancionado)
        .join(Sancionado.documento)
        .options(selectinload(Sancionado.documento))
        .where(and_(*conditions))
        .order_by(BoeDocumento.fecha_publicacion.desc(), Sancionado.id.desc())
    )
    count_statement = select(func.count(Sancionado.id)).join(Sancionado.documento).where(and_(*conditions))
    total = (await db.execute(count_statement)).scalar_one()
    results = (await db.execute(statement.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "items": [_serialise(item).model_dump() for item in results],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/{sancionado_id}", response_model=SancionadoDetail)
async def get_sancion(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sancionado).options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos)).where(Sancionado.id == sancionado_id))
    sancionado = result.scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    detail = SancionadoDetail.model_validate(_serialise(sancionado).model_dump())
    detail.seguimientos = [SeguimientoOut.model_validate(item) for item in sancionado.seguimientos]
    return detail


@router.patch("/{sancionado_id}", response_model=SancionadoDetail)
async def update_sancion(sancionado_id: int, data: SancionadoUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sancionado).options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos)).where(Sancionado.id == sancionado_id))
    sancionado = result.scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    for field in data.model_fields_set:
        setattr(sancionado, field, getattr(data, field))
    await db.commit()
    refreshed = (await db.execute(
        select(Sancionado)
        .options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos))
        .where(Sancionado.id == sancionado_id)
    )).scalar_one()
    detail = SancionadoDetail.model_validate(_serialise(refreshed).model_dump())
    detail.seguimientos = [SeguimientoOut.model_validate(item) for item in refreshed.seguimientos]
    return detail


@router.post("/{sancionado_id}/seguimientos", response_model=SeguimientoOut)
async def add_seguimiento(sancionado_id: int, data: SeguimientoCreate, db: AsyncSession = Depends(get_db)):
    if not (await db.execute(select(Sancionado.id).where(Sancionado.id == sancionado_id))).scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    seguimiento = Seguimiento(sancionado_id=sancionado_id, nota=data.nota, estado=data.estado)
    db.add(seguimiento)
    await db.commit()
    await db.refresh(seguimiento)
    return SeguimientoOut.model_validate(seguimiento)


@router.get("/{sancionado_id}/seguimientos", response_model=list[SeguimientoOut])
async def list_seguimientos(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seguimiento).where(Seguimiento.sancionado_id == sancionado_id).order_by(Seguimiento.created_at.desc()))
    return [SeguimientoOut.model_validate(item) for item in result.scalars().all()]
