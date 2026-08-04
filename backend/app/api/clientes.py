"""API endpoints for the Clientes/CRM core."""

from __future__ import annotations

import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.sanciones import _build_url_documento
from app.config import settings
from app.database import SyncSessionLocal, get_db
from app.models.cliente import AccionAgendada, ActividadCliente, Cliente, NotaCliente, VinculoCliente
from app.models.documento import BoeDocumento
from app.models.documentos_comerciales import DocumentoComercial
from app.models.historico import HistoricoDoc, HistoricoResultado
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
    VinculoCreate,
    VinculoOut,
    VinculoUpdate,
)
from app.schemas.documentos_comerciales import (
    ContratoGenerarRequest,
    DocumentoComercialOut,
    FacturaGenerarRequest,
    ValidacionOut,
)
from app.schemas.historico import (
    ClienteHistoricoBuscarRequest,
    ClienteHistoricoBuscarResponse,
    CoberturaTeuOut,
    HistoricoExtraerRequest,
    HistoricoResultadoOut,
)
from app.services.alertas import ejecutar_radar_clientes
from app.services.clientes import deuda_pendiente_eur
from app.services.documentos_comerciales import (
    DatosFaltantesError,
    generar_contrato,
    generar_factura,
    validar_estructural,
)
from app.services.historico.busqueda import buscar_historico
from app.services.historico.teu_publico import fuera_de_ventana_teu
from app.tasks.historico_extraccion import extraer_historico_task

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


def _historico_resultado_dict(
    resultado: HistoricoResultado, doc: HistoricoDoc, *, hoy: date, titular: str | None = None
) -> dict:
    return {
        "id": resultado.id, "cliente_id": resultado.cliente_id, "historico_doc_id": resultado.historico_doc_id,
        "vinculo_id": resultado.vinculo_id,
        "score": float(resultado.score), "via_match": resultado.via_match, "estado": resultado.estado,
        "extraido": resultado.extraido, "datos_extraidos": resultado.datos_extraidos,
        "created_at": resultado.created_at,
        "boe_id": doc.boe_id, "fuente": doc.fuente, "fecha_publicacion": doc.fecha_publicacion,
        "titulo": doc.titulo, "url_pdf": doc.url_pdf, "url_html": doc.url_html, "url_xml": doc.url_xml,
        "fuera_de_ventana_teu": doc.fuente == "teu" and fuera_de_ventana_teu(doc.fecha_publicacion, hoy=hoy),
        "titular": titular,
    }


def _titular_map(cliente: Cliente, vinculos: list[VinculoCliente]) -> dict[int | None, str]:
    """Maps a vínculo id (or ``None`` for the client itself) to a display
    name, for grouping sanciones/histórico by who they actually belong to."""
    mapa: dict[int | None, str] = {None: cliente.nombre_razon_social}
    for vinculo in vinculos:
        mapa[vinculo.id] = vinculo.nombre or f"{cliente.nombre_razon_social} ({vinculo.rol})"
    return mapa


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
    vinculos_result = await db.execute(
        select(VinculoCliente).where(VinculoCliente.cliente_id == cliente_id).order_by(VinculoCliente.id)
    )
    vinculos = list(vinculos_result.scalars().all())
    titulares = _titular_map(cliente, vinculos)

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
        item.titular = titulares.get(sancionado.vinculo_id, cliente.nombre_razon_social)
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
    detail.vinculos = [VinculoOut.model_validate(item) for item in vinculos]
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


@router.get("/{cliente_id}/vinculos", response_model=list[VinculoOut])
async def list_vinculos(cliente_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    result = await db.execute(
        select(VinculoCliente).where(VinculoCliente.cliente_id == cliente_id).order_by(VinculoCliente.id)
    )
    return [VinculoOut.model_validate(item) for item in result.scalars().all()]


@router.post("/{cliente_id}/vinculos", response_model=VinculoOut)
async def add_vinculo(cliente_id: int, data: VinculoCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    if data.cliente_vinculado_id is not None and await db.get(Cliente, data.cliente_vinculado_id) is None:
        raise HTTPException(status_code=404, detail="cliente_vinculado_id no corresponde a un cliente existente")

    vinculo = VinculoCliente(
        cliente_id=cliente_id, cliente_vinculado_id=data.cliente_vinculado_id, rol=data.rol,
        nombre=data.nombre, tipo_persona=data.tipo_persona, identificador=data.identificador,
        tipo_identificador=data.tipo_identificador, telefono=data.telefono, email=data.email, notas=data.notas,
    )
    db.add(vinculo)
    db.add(ActividadCliente(
        cliente_id=cliente_id, tipo="sistema",
        titulo=f"Vínculo añadido: {data.nombre or 'ficha vinculada'} ({data.rol})",
    ))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe un vínculo con ese identificador para este cliente."
        ) from exc
    await db.refresh(vinculo)
    return VinculoOut.model_validate(vinculo)


@router.patch("/{cliente_id}/vinculos/{vinculo_id}", response_model=VinculoOut)
async def update_vinculo(cliente_id: int, vinculo_id: int, data: VinculoUpdate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    vinculo = await db.get(VinculoCliente, vinculo_id)
    if vinculo is None or vinculo.cliente_id != cliente_id:
        raise HTTPException(status_code=404, detail="Vínculo no encontrado")
    if "cliente_vinculado_id" in data.model_fields_set and data.cliente_vinculado_id is not None:
        if await db.get(Cliente, data.cliente_vinculado_id) is None:
            raise HTTPException(status_code=404, detail="cliente_vinculado_id no corresponde a un cliente existente")
    for field in data.model_fields_set:
        setattr(vinculo, field, getattr(data, field))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Ya existe un vínculo con ese identificador para este cliente."
        ) from exc
    await db.refresh(vinculo)
    return VinculoOut.model_validate(vinculo)


@router.delete("/{cliente_id}/vinculos/{vinculo_id}", response_model=dict)
async def delete_vinculo(cliente_id: int, vinculo_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    vinculo = await db.get(VinculoCliente, vinculo_id)
    if vinculo is None or vinculo.cliente_id != cliente_id:
        raise HTTPException(status_code=404, detail="Vínculo no encontrado")
    await db.delete(vinculo)
    await db.commit()
    return {"deleted": True}


@router.post("/alertas/radar", response_model=dict)
async def ejecutar_radar_alertas(db: AsyncSession = Depends(get_db)):
    """Manually trigger the free radar over the historical index (see
    services/alertas.py). The daily pipeline already runs it automatically at
    the end of every scraping run — this exists for on-demand use."""

    def _run() -> dict[str, int]:
        sync_db = SyncSessionLocal()
        try:
            return ejecutar_radar_clientes(sync_db)
        finally:
            sync_db.close()

    return await run_in_threadpool(_run)


@router.post("/{cliente_id}/historico/buscar", response_model=ClienteHistoricoBuscarResponse)
async def buscar_historico_cliente(
    cliente_id: int, data: ClienteHistoricoBuscarRequest, db: AsyncSession = Depends(get_db)
):
    """Search the historical index for this client's identifiers/plates/name
    and persist the matches. Idempotent — see services/historico/busqueda.py."""
    await _get_or_404(db, cliente_id)

    def _run() -> dict | None:
        sync_db = SyncSessionLocal()
        try:
            cliente_sync = sync_db.get(Cliente, cliente_id)
            if cliente_sync is None:
                return None
            resultado = buscar_historico(sync_db, cliente_sync, incluir_teu=data.incluir_teu)
            titulares = _titular_map(cliente_sync, list(cliente_sync.vinculos))
            hoy = date.today()
            items = [
                _historico_resultado_dict(
                    r, r.documento, hoy=hoy, titular=titulares.get(r.vinculo_id, cliente_sync.nombre_razon_social)
                )
                for r in resultado["resultados"]
            ]
            return {"resultados": items, "avisos": resultado["avisos"], "cobertura_teu": resultado["cobertura_teu"]}
        finally:
            sync_db.close()

    payload = await run_in_threadpool(_run)
    if payload is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return ClienteHistoricoBuscarResponse(
        resultados=[HistoricoResultadoOut(**item) for item in payload["resultados"]],
        avisos=payload["avisos"],
        cobertura_teu=CoberturaTeuOut(**payload["cobertura_teu"]),
    )


@router.get("/{cliente_id}/historico", response_model=list[HistoricoResultadoOut])
async def list_historico_cliente(cliente_id: int, db: AsyncSession = Depends(get_db)):
    cliente = await _get_or_404(db, cliente_id)
    vinculos_result = await db.execute(
        select(VinculoCliente).where(VinculoCliente.cliente_id == cliente_id)
    )
    titulares = _titular_map(cliente, list(vinculos_result.scalars().all()))
    result = await db.execute(
        select(HistoricoResultado, HistoricoDoc)
        .join(HistoricoDoc, HistoricoResultado.historico_doc_id == HistoricoDoc.id)
        .where(HistoricoResultado.cliente_id == cliente_id)
        .order_by(HistoricoResultado.score.desc())
    )
    hoy = date.today()
    return [
        HistoricoResultadoOut(**_historico_resultado_dict(
            resultado, doc, hoy=hoy, titular=titulares.get(resultado.vinculo_id, cliente.nombre_razon_social)
        ))
        for resultado, doc in result.all()
    ]


@router.post("/{cliente_id}/historico/extraer", response_model=dict)
async def extraer_historico_cliente(
    cliente_id: int, data: HistoricoExtraerRequest, db: AsyncSession = Depends(get_db)
):
    """Queue on-demand OpenAI extraction over selected historical results.
    Same two gates as the daily pipeline's paid extraction: explicit
    confirmation here, and openai_extraction_enabled + API key server-side."""
    await _get_or_404(db, cliente_id)
    if not data.confirmar:
        raise HTTPException(status_code=422, detail="Debe confirmar explícitamente la extracción (confirmar=true).")
    if data.permitir_extraccion_pago and (not settings.openai_extraction_enabled or not settings.openai_api_key):
        raise HTTPException(
            status_code=409,
            detail="La extracción OpenAI está deshabilitada; active configuración y API key antes de confirmarla.",
        )
    resultado_ids = list(dict.fromkeys(data.resultado_ids))
    owned = (
        await db.execute(
            select(func.count(HistoricoResultado.id)).where(
                HistoricoResultado.id.in_(resultado_ids), HistoricoResultado.cliente_id == cliente_id,
            )
        )
    ).scalar_one()
    if owned != len(resultado_ids):
        raise HTTPException(status_code=404, detail="Alguno de los resultados no pertenece a este cliente.")
    task = extraer_historico_task.delay(
        resultado_ids, permitir_extraccion_pago=data.permitir_extraccion_pago, force=data.force
    )
    return {"task_id": task.id, "status": "queued", "resultado_ids": resultado_ids}


@router.get("/{cliente_id}/documentos", response_model=list[DocumentoComercialOut])
async def list_documentos_cliente(cliente_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)
    result = await db.execute(
        select(DocumentoComercial)
        .where(DocumentoComercial.cliente_id == cliente_id)
        .order_by(DocumentoComercial.created_at.desc())
    )
    return [DocumentoComercialOut.model_validate(item) for item in result.scalars().all()]


@router.get("/{cliente_id}/documentos/validar", response_model=ValidacionOut)
async def validar_documento_cliente(
    cliente_id: int, tipo: str = Query(..., pattern="^(contrato|factura)$"), db: AsyncSession = Depends(get_db)
):
    """Preview of missing data before generating a contrato/factura — used by
    the UI to render a checklist instead of a bare 422 after the fact."""
    await _get_or_404(db, cliente_id)

    def _run() -> list[dict]:
        sync_db = SyncSessionLocal()
        try:
            cliente_sync = sync_db.get(Cliente, cliente_id)
            faltantes = validar_estructural(sync_db, tipo, cliente_sync)
            return [f.to_dict() for f in faltantes]
        finally:
            sync_db.close()

    faltantes = await run_in_threadpool(_run)
    return ValidacionOut(listo=not faltantes, faltantes=faltantes)


@router.post("/{cliente_id}/contrato", response_model=DocumentoComercialOut)
async def crear_contrato(cliente_id: int, data: ContratoGenerarRequest, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)

    def _run():
        sync_db = SyncSessionLocal()
        try:
            cliente_sync = sync_db.get(Cliente, cliente_id)
            return generar_contrato(sync_db, cliente_sync, precio=data.precio)
        finally:
            sync_db.close()

    try:
        documento = await run_in_threadpool(_run)
    except DatosFaltantesError as exc:
        raise HTTPException(status_code=422, detail=[f.to_dict() for f in exc.faltantes]) from exc
    return DocumentoComercialOut.model_validate(documento)


@router.post("/{cliente_id}/factura", response_model=DocumentoComercialOut)
async def crear_factura(cliente_id: int, data: FacturaGenerarRequest, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, cliente_id)

    def _run():
        sync_db = SyncSessionLocal()
        try:
            cliente_sync = sync_db.get(Cliente, cliente_id)
            return generar_factura(sync_db, cliente_sync, cuantia=data.cuantia, concepto=data.concepto)
        finally:
            sync_db.close()

    try:
        documento = await run_in_threadpool(_run)
    except DatosFaltantesError as exc:
        raise HTTPException(status_code=422, detail=[f.to_dict() for f in exc.faltantes]) from exc
    return DocumentoComercialOut.model_validate(documento)
