"""API endpoints for sanctions and sanctioned entities."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.models.seguimiento import Seguimiento
from app.schemas.sancionado import (
    SancionadoDetail,
    SancionadoOut,
    SeguimientoCreate,
    SeguimientoOut,
)

BOE_BASE = "https://www.boe.es"


def _build_url_documento(doc: BoeDocumento) -> str:
    """Build a full clickable URL for any BOE document."""
    if doc.url_html:
        raw = doc.url_html
        return raw if raw.startswith("http") else f"{BOE_BASE}{raw}"
    if doc.url_pdf:
        raw = doc.url_pdf
        return raw if raw.startswith("http") else f"{BOE_BASE}{raw}"
    if doc.boe_id.startswith("BOE-N-"):
        return f"{BOE_BASE}/boe_n/dias/{doc.fecha_publicacion.year}/{doc.fecha_publicacion.month:02d}/{doc.fecha_publicacion.day:02d}/not.php?id={doc.boe_id}"
    return f"{BOE_BASE}/diario_boe/txt.php?id={doc.boe_id}"

router = APIRouter(prefix="/api/sanciones", tags=["sanciones"])


@router.get("", response_model=dict)
async def list_sanciones(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    organismo: str | None = None,
    tipo_infraccion: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    estado: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Sancionado)
        .join(BoeDocumento, Sancionado.boe_document_id == BoeDocumento.id)
        .order_by(Sancionado.created_at.desc())
    )
    count_query = (
        select(func.count(Sancionado.id))
        .join(BoeDocumento, Sancionado.boe_document_id == BoeDocumento.id)
    )

    if search:
        pattern = f"%{search}%"
        filter_cond = (
            Sancionado.nombre.ilike(pattern)
            | Sancionado.identificador.ilike(pattern)
            | Sancionado.expediente.ilike(pattern)
        )
        query = query.where(filter_cond)
        count_query = count_query.where(filter_cond)

    if organismo:
        query = query.where(Sancionado.organismo_emisor.ilike(f"%{organismo}%"))
        count_query = count_query.where(Sancionado.organismo_emisor.ilike(f"%{organismo}%"))

    if tipo_infraccion:
        query = query.where(Sancionado.tipo_infraccion == tipo_infraccion)
        count_query = count_query.where(Sancionado.tipo_infraccion == tipo_infraccion)

    if fecha_desde:
        query = query.where(BoeDocumento.fecha_publicacion >= fecha_desde)
        count_query = count_query.where(BoeDocumento.fecha_publicacion >= fecha_desde)

    if fecha_hasta:
        query = query.where(BoeDocumento.fecha_publicacion <= fecha_hasta)
        count_query = count_query.where(BoeDocumento.fecha_publicacion <= fecha_hasta)

    if estado:
        subq = select(Seguimiento.sancionado_id).where(Seguimiento.estado == estado).distinct()
        query = query.where(Sancionado.id.in_(subq))
        count_query = count_query.where(Sancionado.id.in_(subq))

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    results = (await db.execute(query.offset(offset).limit(page_size))).scalars().all()

    items = []
    for s in results:
        doc = (await db.execute(
            select(BoeDocumento).where(BoeDocumento.id == s.boe_document_id)
        )).scalar_one_or_none()

        item = SancionadoOut.model_validate(s)
        if doc:
            item.boe_id = doc.boe_id
            item.fecha_publicacion = str(doc.fecha_publicacion)
            item.titulo_documento = doc.titulo
            item.url_html = doc.url_html
            item.url_documento = _build_url_documento(doc)
        items.append(item)

    return {
        "items": [i.model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 0,
    }


@router.get("/{sancionado_id}", response_model=SancionadoDetail)
async def get_sancion(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Sancionado)
        .options(selectinload(Sancionado.seguimientos))
        .where(Sancionado.id == sancionado_id)
    )
    sancionado = result.scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")

    doc = (await db.execute(
        select(BoeDocumento).where(BoeDocumento.id == sancionado.boe_document_id)
    )).scalar_one_or_none()

    detail = SancionadoDetail.model_validate(sancionado)
    if doc:
        detail.boe_id = doc.boe_id
        detail.fecha_publicacion = str(doc.fecha_publicacion)
        detail.titulo_documento = doc.titulo
        detail.url_html = doc.url_html
        detail.url_documento = _build_url_documento(doc)
    return detail


@router.post("/{sancionado_id}/seguimientos", response_model=SeguimientoOut)
async def add_seguimiento(
    sancionado_id: int,
    data: SeguimientoCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Sancionado).where(Sancionado.id == sancionado_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")

    seg = Seguimiento(
        sancionado_id=sancionado_id,
        nota=data.nota,
        estado=data.estado,
    )
    db.add(seg)
    await db.commit()
    await db.refresh(seg)
    return SeguimientoOut.model_validate(seg)


@router.get("/{sancionado_id}/seguimientos", response_model=list[SeguimientoOut])
async def list_seguimientos(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Seguimiento)
        .where(Seguimiento.sancionado_id == sancionado_id)
        .order_by(Seguimiento.created_at.desc())
    )
    return [SeguimientoOut.model_validate(s) for s in result.scalars().all()]
