"""API endpoints for operational opportunities."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.archivo import DocumentoArchivo
from app.models.cliente import Cliente
from app.models.documento import BoeDocumento
from app.models.enriquecimiento import EnriquecimientoIntento
from app.models.sancionado import Sancionado
from app.models.seguimiento import Seguimiento
from app.schemas.cliente import ClienteOut
from app.schemas.sancionado import (
    CONTACT_FIELDS,
    EnriquecimientoIntentoOut,
    SancionadoDetail,
    SancionadoOut,
    SancionadoUpdate,
    SeguimientoCreate,
    SeguimientoOut,
)
from app.services.clientes import convertir_oportunidad, deuda_pendiente_eur
from app.services.enrichment.service import enrichment_available
from app.tasks.enrichment import enrich_sancionado_task

BOE_BASE = "https://www.boe.es"
router = APIRouter(prefix="/api/sanciones", tags=["sanciones"])

_OPPORTUNITY_STATE = "nueva|revisada|contactada|descartada|cliente"


def _build_url_documento(doc: BoeDocumento) -> str:
    if doc.url_html:
        return doc.url_html if doc.url_html.startswith("http") else f"{BOE_BASE}{doc.url_html}"
    if doc.url_pdf:
        return doc.url_pdf if doc.url_pdf.startswith("http") else f"{BOE_BASE}{doc.url_pdf}"
    if doc.boe_id.startswith("BOE-N-"):
        return f"{BOE_BASE}/boe_n/dias/{doc.fecha_publicacion.year}/{doc.fecha_publicacion.month:02d}/{doc.fecha_publicacion.day:02d}/not.php?id={doc.boe_id}"
    return f"{BOE_BASE}/diario_boe/txt.php?id={doc.boe_id}"


async def _boe_ids_archivados(db: AsyncSession, docs: list[BoeDocumento]) -> set[str]:
    boe_ids = [doc.boe_id for doc in docs if doc.boe_id]
    if not boe_ids:
        return set()
    result = await db.execute(select(DocumentoArchivo.boe_id).where(DocumentoArchivo.boe_id.in_(boe_ids)))
    return set(result.scalars().all())


def _serialise(sancionado: Sancionado, *, archivado: bool = False) -> SancionadoOut:
    item = SancionadoOut.model_validate(sancionado)
    doc = sancionado.documento
    item.boe_id = doc.boe_id
    item.fecha_publicacion = str(doc.fecha_publicacion)
    item.titulo_documento = doc.titulo
    item.url_html = doc.url_html
    item.url_documento = _build_url_documento(doc)
    item.tiene_copia_local = archivado or bool(doc.texto_plano)
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
    contacto_estado: str | None = Query(None, pattern="^(pendiente|encontrado|no_encontrado|manual|sin_datos)$"),
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
    if contacto_estado:
        conditions.append(Sancionado.contacto_estado == contacto_estado)
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
    archivados = await _boe_ids_archivados(db, [item.documento for item in results])
    return {
        "items": [_serialise(item, archivado=item.documento.boe_id in archivados).model_dump() for item in results],
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
    archivados = await _boe_ids_archivados(db, [sancionado.documento])
    detail = SancionadoDetail.model_validate(
        _serialise(sancionado, archivado=sancionado.documento.boe_id in archivados).model_dump()
    )
    detail.seguimientos = [SeguimientoOut.model_validate(item) for item in sancionado.seguimientos]
    return detail


def _apply_manual_contact_marking(sancionado: Sancionado, data: SancionadoUpdate) -> None:
    """Whenever a PATCH touches a contact field, (re)derive contacto_estado.

    A non-empty telefono/email after the edit means a human just confirmed the
    contact by hand: mark it "manual" so automatic enrichment never overwrites
    it. If the edit clears both core contact fields, release that lock back to
    "pendiente" so the opportunity is eligible for enrichment again.
    """
    if not CONTACT_FIELDS & data.model_fields_set:
        return
    if sancionado.telefono or sancionado.email:
        sancionado.contacto_estado = "manual"
        sancionado.contacto_fuente = "manual"
        sancionado.contacto_confidence = 1.0
        sancionado.contacto_actualizado_at = datetime.now(timezone.utc)
    else:
        sancionado.contacto_estado = "pendiente"
        sancionado.contacto_fuente = None
        sancionado.contacto_url = None
        sancionado.contacto_confidence = None
        sancionado.contacto_actualizado_at = None


@router.patch("/{sancionado_id}", response_model=SancionadoDetail)
async def update_sancion(sancionado_id: int, data: SancionadoUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sancionado).options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos)).where(Sancionado.id == sancionado_id))
    sancionado = result.scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    for field in data.model_fields_set:
        setattr(sancionado, field, getattr(data, field))
    _apply_manual_contact_marking(sancionado, data)
    await db.commit()
    refreshed = (await db.execute(
        select(Sancionado)
        .options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos))
        .where(Sancionado.id == sancionado_id)
    )).scalar_one()
    archivados = await _boe_ids_archivados(db, [refreshed.documento])
    detail = SancionadoDetail.model_validate(
        _serialise(refreshed, archivado=refreshed.documento.boe_id in archivados).model_dump()
    )
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


@router.post("/{sancionado_id}/enriquecer", response_model=dict)
async def enrich_sancion(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    """Queue a single on-demand enrichment attempt. Same cost-gate pattern as
    the sesion 1 scraping trigger: a clear 409 if disabled/unconfigured, never
    a silent no-op.

    Also doubles as the "I've looked at this opportunity" marker: the user
    reaching for this button is exactly the moment they start working a lead,
    so a still-"nueva" opportunity advances to "revisada" right away — this is
    what lets the list filter/URL-persistence surface "leads already touched"
    without a separate flag.
    """
    sancionado = (await db.execute(select(Sancionado).where(Sancionado.id == sancionado_id))).scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    available, reason = enrichment_available()
    if not available:
        raise HTTPException(status_code=409, detail=reason)
    if sancionado.estado_oportunidad == "nueva":
        sancionado.estado_oportunidad = "revisada"
        await db.commit()
    task = enrich_sancionado_task.delay(sancionado_id)
    return {"task_id": task.id, "status": "queued", "estado_oportunidad": sancionado.estado_oportunidad}


@router.get("/{sancionado_id}/enriquecimiento", response_model=list[EnriquecimientoIntentoOut])
async def list_enrichment_attempts(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EnriquecimientoIntento)
        .where(EnriquecimientoIntento.sancionado_id == sancionado_id)
        .order_by(EnriquecimientoIntento.created_at.desc())
    )
    return [EnriquecimientoIntentoOut.model_validate(item) for item in result.scalars().all()]


@router.post("/{sancionado_id}/convertir", response_model=dict)
async def convertir_a_cliente(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    """Convert an opportunity into a client. Idempotent: converting the same
    opportunity twice returns the same Cliente with ``created: false`` the
    second time, never a duplicate — see services/clientes.convertir_oportunidad
    for the in-request check and the ``sancion_origen_id`` unique constraint
    that backs it up under concurrent requests."""
    result = await db.execute(select(Sancionado).where(Sancionado.id == sancionado_id))
    sancionado = result.scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    try:
        cliente, created = await convertir_oportunidad(db, sancionado)
        await db.commit()
    except IntegrityError:
        # Two concurrent requests raced past the pre-check in convertir_oportunidad;
        # the unique constraint on sancion_origen_id is the real guarantee here.
        await db.rollback()
        cliente = (
            await db.execute(select(Cliente).where(Cliente.sancion_origen_id == sancionado_id))
        ).scalar_one()
        created = False
    out = ClienteOut.model_validate(cliente)
    out.deuda_pendiente_eur = await deuda_pendiente_eur(db, cliente.id)
    return {"cliente": out.model_dump(), "created": created}
