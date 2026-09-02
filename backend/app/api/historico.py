"""API endpoints for the historical index: manual double-gated backfill,
read-only internal consultation, and the archive listing.

Every endpoint that can trigger real work (the backfill) requires an explicit
``confirmar=true`` plus a range-and-limits-bound confirmation token that must
match a plan requested moments earlier — see
``app/tasks/historico_backfill.py``. Nothing here is reachable without that
handshake, and nothing here is on a schedule.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import SyncSessionLocal, get_db
from app.api.documentos import _respuesta_copia_local
from app.models.archivo import DocumentoArchivo
from app.models.historico import HistoricoBackfillRun, HistoricoDoc
from app.schemas.historico import (
    BackfillPlanOut,
    BackfillPlanRequest,
    BackfillRequest,
    BackfillRunOut,
    CoberturaTeuOut,
    ConsultaRequest,
    ConsultaResponse,
    HistoricoCoberturaOut,
)
from app.services.historico.busqueda import consultar_historico
from app.services.historico.teu_publico import fuera_de_ventana_teu, ventana_publica_desde
from app.tasks.historico_backfill import backfill_available, plan_backfill, run_backfill_task, token_confirmacion

router = APIRouter(prefix="/api/historico", tags=["historico"])


@router.post("/backfill/plan", response_model=BackfillPlanOut)
async def preview_backfill(data: BackfillPlanRequest):
    """Pure arithmetic preview: no network access, no database writes."""
    return plan_backfill(data.fecha_desde, data.fecha_hasta)


@router.post("/backfill", response_model=dict)
async def lanzar_backfill(data: BackfillRequest):
    if not data.confirmar:
        raise HTTPException(
            status_code=422,
            detail="Debe confirmar explícitamente (confirmar=true) el rango previsualizado.",
        )
    disponible, motivo = backfill_available()
    if not disponible:
        raise HTTPException(status_code=409, detail=motivo)
    esperado = token_confirmacion(
        data.fecha_desde, data.fecha_hasta,
        settings.historico_backfill_max_dias_por_lote, settings.historico_backfill_max_docs_por_lote,
    )
    if data.confirmacion != esperado:
        raise HTTPException(
            status_code=422,
            detail=(
                "El token de confirmación no coincide con el rango y los límites configurados. "
                "Solicite un nuevo plan (POST /api/historico/backfill/plan) y confirme exactamente ese rango."
            ),
        )
    task = run_backfill_task.delay(
        data.fecha_desde.isoformat(), data.fecha_hasta.isoformat(), data.confirmacion,
        max_dias=data.max_dias, max_documentos=data.max_documentos,
    )
    return {
        "task_id": task.id, "status": "queued",
        "fecha_desde": data.fecha_desde.isoformat(), "fecha_hasta": data.fecha_hasta.isoformat(),
    }


@router.get("/backfill/runs", response_model=list[BackfillRunOut])
async def list_backfill_runs(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HistoricoBackfillRun).order_by(HistoricoBackfillRun.created_at.desc()).limit(limit)
    )
    return [BackfillRunOut.model_validate(r) for r in result.scalars().all()]


@router.get("/backfill/status/{task_id}", response_model=dict)
async def backfill_status(task_id: str):
    result = run_backfill_task.AsyncResult(task_id)
    return {"task_id": task_id, "status": result.status, "result": result.result if result.ready() else None}


@router.post("/consulta", response_model=ConsultaResponse)
async def consulta(data: ConsultaRequest):
    """Internal "Consulta por DNI/CIF" screen. Read-only over the index; TEU
    is only queried live when ``incluir_teu`` is explicitly true AND the
    connector is enabled and configured (checked inside the service)."""

    def _run() -> dict:
        sync_db = SyncSessionLocal()
        try:
            return consultar_historico(
                sync_db, cif=data.cif, dni=data.dni, matricula=data.matricula, nombre=data.nombre,
                incluir_teu=data.incluir_teu,
            )
        finally:
            sync_db.close()

    resultado = await run_in_threadpool(_run)
    return ConsultaResponse(
        resultados=resultado["resultados"], avisos=resultado["avisos"],
        cobertura_teu=CoberturaTeuOut(**resultado["cobertura_teu"]),
    )


@router.get("/cobertura", response_model=HistoricoCoberturaOut)
async def cobertura(db: AsyncSession = Depends(get_db)):
    """States what is ACTUALLY indexed, not what was intended — computed
    directly from historico_docs rather than from configuration."""
    boe_desde, boe_hasta, boe_dias = (
        await db.execute(
            select(
                func.min(HistoricoDoc.fecha_publicacion), func.max(HistoricoDoc.fecha_publicacion),
                func.count(func.distinct(HistoricoDoc.fecha_publicacion)),
            ).where(HistoricoDoc.fuente == "boe")
        )
    ).one()
    teu_desde, teu_hasta, teu_dias = (
        await db.execute(
            select(
                func.min(HistoricoDoc.fecha_publicacion), func.max(HistoricoDoc.fecha_publicacion),
                func.count(func.distinct(HistoricoDoc.fecha_publicacion)),
            ).where(HistoricoDoc.fuente == "teu")
        )
    ).one()
    total = (await db.execute(select(func.count(HistoricoDoc.id)))).scalar_one()
    return HistoricoCoberturaOut(
        boe_desde=boe_desde, boe_hasta=boe_hasta, boe_dias_indexados=boe_dias or 0,
        teu_desde=teu_desde, teu_hasta=teu_hasta, teu_dias_indexados=teu_dias or 0,
        total_documentos=total, ventana_publica_teu_desde=ventana_publica_desde().isoformat(),
    )


@router.get("", response_model=dict)
async def list_historico(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    fuente: str | None = Query(None, pattern="^(boe|teu)$"),
    anio: int | None = Query(None, ge=1960, le=2100),
    db: AsyncSession = Depends(get_db),
):
    """Archive listing for the "Historial" screen."""
    conditions = []
    if fuente:
        conditions.append(HistoricoDoc.fuente == fuente)
    if anio:
        conditions.append(func.extract("year", HistoricoDoc.fecha_publicacion) == anio)

    statement = select(HistoricoDoc).where(and_(*conditions)).order_by(HistoricoDoc.fecha_publicacion.desc())
    count_statement = select(func.count(HistoricoDoc.id)).where(and_(*conditions))
    total = (await db.execute(count_statement)).scalar_one()
    results = (await db.execute(statement.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    hoy = date.today()
    archivados = set(
        (await db.execute(
            select(DocumentoArchivo.boe_id).where(
                DocumentoArchivo.boe_id.in_([d.boe_id for d in results])
            )
        )).scalars().all()
    ) if results else set()
    items = [
        {
            "id": d.id, "boe_id": d.boe_id, "fuente": d.fuente,
            "fecha_publicacion": d.fecha_publicacion.isoformat(), "titulo": d.titulo,
            "departamento_nombre": d.departamento_nombre, "url_pdf": d.url_pdf, "url_html": d.url_html,
            "url_xml": d.url_xml, "origen_indexado": d.origen_indexado,
            "fuera_de_ventana_teu": d.fuente == "teu" and fuera_de_ventana_teu(d.fecha_publicacion, hoy=hoy),
            "tiene_copia_local": d.boe_id in archivados or bool(d.texto_plano or d.extracto),
        }
        for d in results
    ]
    return {
        "items": items, "total": total, "page": page, "page_size": page_size,
        "pages": -(-total // page_size) if total else 0,
    }


@router.get("/{doc_id}/archivo")
async def get_historico_archivo(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = (await db.execute(select(HistoricoDoc).where(HistoricoDoc.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    archivo = (await db.execute(
        select(DocumentoArchivo).where(DocumentoArchivo.boe_id == doc.boe_id)
    )).scalar_one_or_none()
    return _respuesta_copia_local(archivo, doc.texto_plano or doc.extracto, doc.boe_id)
