"""API endpoints for the Clientes/CRM core."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.sanciones import _build_url_documento
from app.database import get_db
from app.models.cliente import AccionAgendada, ActividadCliente, Cliente, NotaCliente
from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.schemas.cliente import (
    AccionAgendadaCreate,
    AccionAgendadaOut,
    AccionAgendadaUpdate,
    ActividadClienteOut,
    ClienteDetail,
    ClienteOut,
    ClienteUpdate,
    NotaClienteCreate,
    NotaClienteOut,
    SancionVinculadaOut,
)
from app.services.clientes import deuda_pendiente_eur

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


async def _serialise_out(db: AsyncSession, cliente: Cliente) -> ClienteOut:
    item = ClienteOut.model_validate(cliente)
    item.deuda_pendiente_eur = await deuda_pendiente_eur(db, cliente.id)
    return item


async def _get_or_404(db: AsyncSession, cliente_id: int) -> Cliente:
    cliente = await db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.get("", response_model=dict)
async def list_clientes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    estado_cliente: str | None = Query(None, pattern="^(activo|inactivo)$"),
    sector: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(
            Cliente.nombre_razon_social.ilike(pattern),
            Cliente.cif_nif.ilike(pattern),
            Cliente.dni_nie.ilike(pattern),
            Cliente.codigo.ilike(pattern),
        ))
    if estado_cliente:
        conditions.append(Cliente.estado_cliente == estado_cliente)
    if sector:
        conditions.append(Cliente.sector.ilike(f"%{sector.strip()}%"))

    statement = select(Cliente).where(and_(*conditions)).order_by(Cliente.created_at.desc())
    count_statement = select(func.count(Cliente.id)).where(and_(*conditions))
    total = (await db.execute(count_statement)).scalar_one()
    results = (await db.execute(statement.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    items = [await _serialise_out(db, item) for item in results]
    return {
        "items": [item.model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/{cliente_id}", response_model=ClienteDetail)
async def get_cliente(cliente_id: int, db: AsyncSession = Depends(get_db)):
    cliente = await _get_or_404(db, cliente_id)
    sanciones_result = await db.execute(
        select(Sancionado)
        .options(selectinload(Sancionado.documento))
        .where(Sancionado.cliente_id == cliente_id)
        .order_by(Sancionado.id.desc())
    )
    sanciones = []
    for sancionado in sanciones_result.scalars().all():
        item = SancionVinculadaOut.model_validate(sancionado)
        doc: BoeDocumento = sancionado.documento
        item.fecha_publicacion = str(doc.fecha_publicacion)
        item.url_documento = _build_url_documento(doc)
        sanciones.append(item)

    notas_result = await db.execute(
        select(NotaCliente).where(NotaCliente.cliente_id == cliente_id).order_by(NotaCliente.created_at.desc())
    )
    actividades_result = await db.execute(
        select(ActividadCliente).where(ActividadCliente.cliente_id == cliente_id).order_by(ActividadCliente.created_at.desc())
    )
    acciones_result = await db.execute(
        select(AccionAgendada).where(AccionAgendada.cliente_id == cliente_id).order_by(AccionAgendada.created_at.desc())
    )

    out = await _serialise_out(db, cliente)
    detail = ClienteDetail.model_validate(out.model_dump())
    detail.sanciones = sanciones
    detail.notas = [NotaClienteOut.model_validate(item) for item in notas_result.scalars().all()]
    detail.actividades = [ActividadClienteOut.model_validate(item) for item in actividades_result.scalars().all()]
    detail.acciones = [AccionAgendadaOut.model_validate(item) for item in acciones_result.scalars().all()]
    return detail


@router.patch("/{cliente_id}", response_model=ClienteOut)
async def update_cliente(cliente_id: int, data: ClienteUpdate, db: AsyncSession = Depends(get_db)):
    cliente = await _get_or_404(db, cliente_id)
    for field in data.model_fields_set:
        setattr(cliente, field, getattr(data, field))
    await db.commit()
    await db.refresh(cliente)
    return await _serialise_out(db, cliente)


@router.get("/{cliente_id}/notas", response_model=list[NotaClienteOut])
async def list_notas(cliente_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    result = await db.execute(
        select(NotaCliente).where(NotaCliente.cliente_id == cliente_id).order_by(NotaCliente.created_at.desc())
    )
    return [NotaClienteOut.model_validate(item) for item in result.scalars().all()]


@router.post("/{cliente_id}/notas", response_model=NotaClienteOut)
async def add_nota(cliente_id: int, data: NotaClienteCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    nota = NotaCliente(cliente_id=cliente_id, texto=data.texto, autor=data.autor)
    db.add(nota)
    db.add(ActividadCliente(cliente_id=cliente_id, tipo="nota", titulo="Nota añadida", detalle=data.texto[:500]))
    await db.commit()
    await db.refresh(nota)
    return NotaClienteOut.model_validate(nota)


@router.get("/{cliente_id}/actividad", response_model=list[ActividadClienteOut])
async def list_actividad(cliente_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    result = await db.execute(
        select(ActividadCliente).where(ActividadCliente.cliente_id == cliente_id).order_by(ActividadCliente.created_at.desc())
    )
    return [ActividadClienteOut.model_validate(item) for item in result.scalars().all()]


@router.get("/{cliente_id}/acciones", response_model=list[AccionAgendadaOut])
async def list_acciones(cliente_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    result = await db.execute(
        select(AccionAgendada).where(AccionAgendada.cliente_id == cliente_id).order_by(AccionAgendada.created_at.desc())
    )
    return [AccionAgendadaOut.model_validate(item) for item in result.scalars().all()]


@router.post("/{cliente_id}/acciones", response_model=AccionAgendadaOut)
async def add_accion(cliente_id: int, data: AccionAgendadaCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    accion = AccionAgendada(
        cliente_id=cliente_id, tipo=data.tipo, titulo=data.titulo,
        fecha_programada=data.fecha_programada, notas=data.notas,
    )
    db.add(accion)
    db.add(ActividadCliente(cliente_id=cliente_id, tipo=data.tipo, titulo=f"Acción agendada: {data.titulo}"))
    await db.commit()
    await db.refresh(accion)
    return AccionAgendadaOut.model_validate(accion)


@router.patch("/{cliente_id}/acciones/{accion_id}", response_model=AccionAgendadaOut)
async def update_accion(cliente_id: int, accion_id: int, data: AccionAgendadaUpdate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    accion = await db.get(AccionAgendada, accion_id)
    if accion is None or accion.cliente_id != cliente_id:
        raise HTTPException(status_code=404, detail="Acción no encontrada")
    for field in data.model_fields_set:
        setattr(accion, field, getattr(data, field))
    await db.commit()
    await db.refresh(accion)
    return AccionAgendadaOut.model_validate(accion)
