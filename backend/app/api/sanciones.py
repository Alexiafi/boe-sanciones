"""API endpoints for operational opportunities."""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

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
    SancionadoCreate,
    SancionadoDetail,
    SancionadoOut,
    SancionadoUpdate,
    SancionRelacionadaOut,
    SeguimientoCreate,
    SeguimientoOut,
    SeguimientoRelacionadoOut,
)
from app.services.boe_client import url_documento_boe
from app.services.clientes import _split_identifier, convertir_oportunidad, deuda_pendiente_eur
from app.services.enrichment.service import enrichment_available
from app.services.historico.patterns import clave_identidad, normalizar_identificador
from app.services.identidad import propagar_edicion_sancionado, resumen_identidades, vincular_sanciones_a_cliente
from app.services.oportunidades import allocate_codigo_async
from app.tasks.enrichment import enrich_sancionado_task

router = APIRouter(prefix="/api/sanciones", tags=["sanciones"])

_OPPORTUNITY_STATE = "nueva|revisada|contactada|descartada|cliente"


def _build_url_documento(doc: BoeDocumento) -> str:
    return url_documento_boe(
        boe_id=doc.boe_id, fecha_publicacion=doc.fecha_publicacion, url_html=doc.url_html, url_pdf=doc.url_pdf,
    )


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


async def _decorar(db: AsyncSession, sancionados: list[Sancionado], salidas: list[SancionadoOut]) -> None:
    """Fill the identity fields of each row: who the party is when the notice
    itself has no name (TEU notices carry only the DNI/CIF), whether it is
    already a client, and whether somebody already worked another notice of it."""
    cliente_ids = {s.cliente_id for s in sancionados if s.cliente_id}
    clientes = {
        c.id: c for c in (await db.execute(select(Cliente).where(Cliente.id.in_(cliente_ids)))).scalars().all()
    } if cliente_ids else {}
    resumen = await resumen_identidades(db, {s.identidad_clave for s in sancionados if s.identidad_clave})
    for sancionado, salida in zip(sancionados, salidas):
        cliente = clientes.get(sancionado.cliente_id) if sancionado.cliente_id else None
        salida.cliente_nombre = cliente.nombre_razon_social if cliente else None
        salida.cliente_estado = cliente.estado_cliente if cliente else None
        # The extraction sometimes puts the DNI/CIF itself in the name field.
        nombre_propio = sancionado.nombre
        if nombre_propio and (sancionado.identificador or "").strip().upper() == nombre_propio.strip().upper():
            nombre_propio = None
        salida.nombre_mostrado = nombre_propio or salida.cliente_nombre or sancionado.identificador
        datos = resumen.get(sancionado.identidad_clave or "")
        if datos:
            propia_contactada = 1 if sancionado.estado_oportunidad == "contactada" else 0
            salida.otras_notificaciones = max(0, datos["notificaciones"] - 1)
            salida.ya_contactado = datos["contactadas"] - propia_contactada > 0
            salida.ultima_gestion = datos["ultima_gestion"]
            salida.notas_del_titular = datos["notas"]


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
    solo_con_telefono: bool | None = None,
    contacto_estado: str | None = Query(None, pattern="^(pendiente|encontrado|no_encontrado|manual|sin_datos)$"),
    es_cliente: bool | None = None,
    gestion_previa: bool | None = None,
    estado: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if cuantia_min is not None and cuantia_max is not None and cuantia_min > cuantia_max:
        raise HTTPException(status_code=422, detail="cuantia_min no puede superar cuantia_max")
    # Looking somebody up (a DNI/CIF, a name) must search everything we have,
    # not just the last 30 days that the panel shows by default.
    if fecha_desde is None and fecha_hasta is None and not (search and search.strip()):
        fecha_hasta = date.today()
        fecha_desde = fecha_hasta - timedelta(days=29)

    conditions = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        clave = normalizar_identificador(search)
        por_identificador = [Sancionado.identificador.ilike(pattern)]
        if clave:
            # "12.345.678-z", "b 12345678"… all find "12345678Z"/"B12345678".
            por_identificador.append(Sancionado.identidad_clave == clave)
            por_identificador.append(
                func.regexp_replace(func.upper(Sancionado.identificador), r"[\s.\-]", "", "g").like(f"%{clave}%")
            )
        conditions.append(or_(
            Sancionado.codigo.ilike(pattern), Sancionado.nombre.ilike(pattern), Sancionado.expediente.ilike(pattern),
            Sancionado.matricula_coche.ilike(pattern), Cliente.nombre_razon_social.ilike(pattern), *por_identificador,
        ))
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
    if solo_con_telefono is True:
        conditions.append(func.nullif(func.trim(Sancionado.telefono), "").isnot(None))
    elif solo_con_telefono is False:
        conditions.append(func.nullif(func.trim(Sancionado.telefono), "").is_(None))
    if contacto_estado:
        conditions.append(Sancionado.contacto_estado == contacto_estado)
    if es_cliente is True:
        conditions.append(Sancionado.cliente_id.is_not(None))
    elif es_cliente is False:
        conditions.append(Sancionado.cliente_id.is_(None))
    if gestion_previa is not None:
        otra = aliased(Sancionado)
        ya_contactada = exists().where(
            otra.identidad_clave == Sancionado.identidad_clave, otra.id != Sancionado.id,
            otra.estado_oportunidad == "contactada",
        )
        conditions.append(ya_contactada if gestion_previa else ~ya_contactada)
    # Compatibility with the pre-session endpoint: this remains a historial
    # filter and does not replace the opportunity state.
    if estado:
        conditions.append(Sancionado.id.in_(select(Seguimiento.sancionado_id).where(Seguimiento.estado == estado).distinct()))

    statement = (
        select(Sancionado)
        .join(Sancionado.documento)
        .outerjoin(Cliente, Cliente.id == Sancionado.cliente_id)
        .options(selectinload(Sancionado.documento))
        .where(and_(*conditions))
        .order_by(BoeDocumento.fecha_publicacion.desc(), Sancionado.id.desc())
    )
    count_statement = (
        select(func.count(Sancionado.id)).join(Sancionado.documento)
        .outerjoin(Cliente, Cliente.id == Sancionado.cliente_id).where(and_(*conditions))
    )
    total = (await db.execute(count_statement)).scalar_one()
    results = (await db.execute(statement.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    archivados = await _boe_ids_archivados(db, [item.documento for item in results])
    salidas = [_serialise(item, archivado=item.documento.boe_id in archivados) for item in results]
    await _decorar(db, list(results), salidas)
    return {
        "items": [salida.model_dump() for salida in salidas],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


async def _detalle(db: AsyncSession, sancionado: Sancionado) -> SancionadoDetail:
    """Full detail of one notice: its own data and notes, plus the history of
    the same party — its other notices and the notes written on them — so that
    whoever opens a new notice sees at once what was already done."""
    archivados = await _boe_ids_archivados(db, [sancionado.documento])
    base = _serialise(sancionado, archivado=sancionado.documento.boe_id in archivados)
    await _decorar(db, [sancionado], [base])
    detalle = SancionadoDetail.model_validate(base.model_dump())
    detalle.seguimientos = [SeguimientoOut.model_validate(item) for item in sancionado.seguimientos]
    if not sancionado.identidad_clave:
        return detalle

    hermanas = (await db.execute(
        select(Sancionado).options(selectinload(Sancionado.documento))
        .where(Sancionado.identidad_clave == sancionado.identidad_clave, Sancionado.id != sancionado.id)
        .order_by(Sancionado.id.desc()).limit(50)
    )).scalars().all()
    notas = (await db.execute(
        select(Seguimiento, Sancionado.codigo)
        .join(Sancionado, Sancionado.id == Seguimiento.sancionado_id)
        .where(Sancionado.identidad_clave == sancionado.identidad_clave, Seguimiento.sancionado_id != sancionado.id)
        .order_by(Seguimiento.created_at.desc()).limit(50)
    )).all()
    ultima_nota: dict[int, str] = {}
    for seguimiento, _codigo in notas:
        if seguimiento.nota and seguimiento.sancionado_id not in ultima_nota:
            ultima_nota[seguimiento.sancionado_id] = seguimiento.nota
    detalle.relacionadas = [
        SancionRelacionadaOut(
            id=h.id, codigo=h.codigo, estado_oportunidad=h.estado_oportunidad,
            fecha_publicacion=str(h.documento.fecha_publicacion), organismo_emisor=h.organismo_emisor,
            expediente=h.expediente,
            importe_multa_eur=float(h.importe_multa_eur) if h.importe_multa_eur is not None else None,
            importe_deuda_eur=float(h.importe_deuda_eur) if h.importe_deuda_eur is not None else None,
            cliente_id=h.cliente_id, ultima_nota=ultima_nota.get(h.id),
        )
        for h in hermanas
    ]
    detalle.seguimientos_relacionados = [
        SeguimientoRelacionadoOut(
            id=seg.id, sancionado_id=seg.sancionado_id, codigo=codigo, nota=seg.nota, estado=seg.estado,
            created_at=seg.created_at,
        )
        for seg, codigo in notas
    ]
    return detalle


@router.post("", response_model=SancionadoDetail, status_code=201)
async def crear_sancion_manual(data: SancionadoCreate, db: AsyncSession = Depends(get_db)):
    """Alta manual de una multa. Opcionalmente convierte en cliente en el mismo paso.

    No pasa por BOE/TEU: se crea un documento sintético (``source=manual``) para
    reutilizar el mismo modelo que las oportunidades extraídas.
    """
    fecha = data.fecha_publicacion or date.today()
    codigo = await allocate_codigo_async(db, fecha.year)
    boe_id = f"MANUAL-{uuid.uuid4().hex[:16].upper()}"
    titulo = data.titulo_documento or f"Alta manual: {data.nombre or data.identificador}"
    documento = BoeDocumento(
        boe_id=boe_id,
        fecha_publicacion=fecha,
        titulo=titulo,
        source="manual",
        extraction_status="completed",
    )
    db.add(documento)
    await db.flush()

    origen_clave = hashlib.sha256(f"manual|{boe_id}".encode("utf-8")).hexdigest()
    sancionado = Sancionado(
        boe_document_id=documento.id,
        codigo=codigo,
        estado_oportunidad="nueva",
        origen_clave=origen_clave,
        nombre=data.nombre,
        tipo_persona=data.tipo_persona,
        identificador=data.identificador,
        tipo_identificador=data.tipo_identificador,
        direccion=data.direccion,
        localidad=data.localidad,
        provincia=data.provincia,
        codigo_postal=data.codigo_postal,
        telefono=data.telefono,
        email=data.email,
        web=data.web,
        matricula_coche=data.matricula_coche,
        importe_multa_eur=data.importe_multa_eur,
        tipo_infraccion=data.tipo_infraccion,
        razon_sancion=data.razon_sancion,
        expediente=data.expediente,
        organismo_emisor=data.organismo_emisor,
        dominio_material=data.dominio_material,
        observaciones=data.observaciones,
    )
    if data.telefono or data.email:
        sancionado.contacto_estado = "manual"
        sancionado.contacto_fuente = "manual"
        sancionado.contacto_confidence = 1.0
        sancionado.contacto_actualizado_at = datetime.now(timezone.utc)
    db.add(sancionado)
    await db.flush()

    if data.crear_cliente:
        cliente, _creado = await convertir_oportunidad(db, sancionado)
        await vincular_sanciones_a_cliente(db, cliente)

    await db.commit()
    refreshed = (
        await db.execute(
            select(Sancionado)
            .options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos))
            .where(Sancionado.id == sancionado.id)
        )
    ).scalar_one()
    return await _detalle(db, refreshed)


@router.get("/{sancionado_id}", response_model=SancionadoDetail)
async def get_sancion(sancionado_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sancionado).options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos)).where(Sancionado.id == sancionado_id))
    sancionado = result.scalar_one_or_none()
    if not sancionado:
        raise HTTPException(status_code=404, detail="Sancionado no encontrado")
    return await _detalle(db, sancionado)


def _apply_manual_contact_marking(sancionado: Sancionado, cambiados: set[str]) -> None:
    """Whenever a PATCH actually CHANGES a contact field, (re)derive
    contacto_estado. (The form sends every field on each save; merely saving
    an enriched record must not turn it into a "manual" one.)

    A non-empty telefono/email after the edit means a human just confirmed the
    contact by hand: mark it "manual" so automatic enrichment never overwrites
    it. If the edit clears both core contact fields, release that lock back to
    "pendiente" so the opportunity is eligible for enrichment again.
    """
    if not CONTACT_FIELDS & cambiados:
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
    if "estado_oportunidad" in data.model_fields_set and data.estado_oportunidad == "cliente" \
            and sancionado.estado_oportunidad != "cliente":
        # Only a conversion (or the automatic assignment) makes a notice a client's.
        raise HTTPException(status_code=422, detail="El estado «cliente» solo se asigna al convertir en cliente.")
    antes = {field: getattr(sancionado, field) for field in data.model_fields_set}
    for field in data.model_fields_set:
        setattr(sancionado, field, getattr(data, field))
    cambiados = {field for field, valor in antes.items() if valor != getattr(sancionado, field)}
    _apply_manual_contact_marking(sancionado, cambiados)
    # An identifier typed by hand is what ties this notice to its party: key it
    # now so the sharing below (and the client link) sees the new value.
    sancionado.identidad_clave = clave_identidad(sancionado.identificador)
    if sancionado.cliente_id and cambiados & {"identificador", "tipo_identificador"}:
        cliente = await db.get(Cliente, sancionado.cliente_id)
        if cliente is not None:
            cif_nif, dni_nie = _split_identifier(sancionado)
            if cif_nif and not cliente.cif_nif:
                cliente.cif_nif = cif_nif
            if dni_nie and not cliente.dni_nie:
                cliente.dni_nie = dni_nie
    # What is typed on one notice is the same person's data on all the others
    # and on the client ficha (and a "contactada" mark spares a second call).
    await propagar_edicion_sancionado(db, sancionado, cambiados, ahora=datetime.now(timezone.utc))
    await db.commit()
    refreshed = (await db.execute(
        select(Sancionado)
        .options(selectinload(Sancionado.documento), selectinload(Sancionado.seguimientos))
        .where(Sancionado.id == sancionado_id)
    )).scalar_one()
    return await _detalle(db, refreshed)


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
        # Every earlier notice of the same DNI/CIF belongs to this client too.
        await vincular_sanciones_a_cliente(db, cliente)
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
