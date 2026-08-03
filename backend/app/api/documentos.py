"""API endpoints for BOE documents."""

from __future__ import annotations

import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.schemas.documento import BoeDocumentoDetail, BoeDocumentoOut

router = APIRouter(prefix="/api/documentos", tags=["documentos"])


@router.get("", response_model=dict)
async def list_documentos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(BoeDocumento).order_by(BoeDocumento.fecha_publicacion.desc())
    count_query = select(func.count(BoeDocumento.id))

    if search:
        pattern = f"%{search}%"
        cond = BoeDocumento.titulo.ilike(pattern) | BoeDocumento.boe_id.ilike(pattern)
        query = query.where(cond)
        count_query = count_query.where(cond)

    if fecha_desde:
        query = query.where(BoeDocumento.fecha_publicacion >= fecha_desde)
        count_query = count_query.where(BoeDocumento.fecha_publicacion >= fecha_desde)
    if fecha_hasta:
        query = query.where(BoeDocumento.fecha_publicacion <= fecha_hasta)
        count_query = count_query.where(BoeDocumento.fecha_publicacion <= fecha_hasta)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * page_size
    results = (await db.execute(query.offset(offset).limit(page_size))).scalars().all()

    items = []
    for doc in results:
        scount = (await db.execute(
            select(func.count(Sancionado.id)).where(Sancionado.boe_document_id == doc.id)
        )).scalar() or 0
        out = BoeDocumentoOut.model_validate(doc)
        out.sancionados_count = scount
        items.append(out)

    return {
        "items": [i.model_dump() for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total > 0 else 0,
    }


@router.get("/{doc_id}", response_model=BoeDocumentoDetail)
async def get_documento(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BoeDocumento).where(BoeDocumento.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return BoeDocumentoDetail.model_validate(doc)
