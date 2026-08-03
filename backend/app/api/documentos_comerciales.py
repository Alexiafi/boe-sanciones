"""API endpoints for issued commercial documents (contrato/factura) that are
addressed by their own id — generation lives on the clientes router
(``POST /api/clientes/{id}/contrato``/``/factura``) since it always needs the
owning client; this router covers listing, downloading the PDF, and sending.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.database import SyncSessionLocal, get_db
from app.models.cliente import ActividadCliente, Cliente
from app.models.documentos_comerciales import DocumentoComercial, PlantillaDocumento
from app.schemas.documentos_comerciales import (
    DocumentoComercialOut,
    EnviarDocumentoRequest,
    PlantillaDocumentoOut,
    PlantillaDocumentoUpdate,
)
from app.services.documentos_comerciales import PROVISIONAL_MARKER
from app.services.mailer import Adjunto, EmailSendingDisabled, email_sending_available, enviar_email

router = APIRouter(prefix="/api/documentos-comerciales", tags=["documentos-comerciales"])


def _plantilla_out(plantilla: PlantillaDocumento) -> PlantillaDocumentoOut:
    return PlantillaDocumentoOut(
        id=plantilla.id, tipo=plantilla.tipo, nombre=plantilla.nombre,
        contenido_html=plantilla.contenido_html, version=plantilla.version, activo=plantilla.activo,
        es_provisional=PROVISIONAL_MARKER in plantilla.contenido_html, created_at=plantilla.created_at,
    )


async def _get_or_404(db: AsyncSession, documento_id: int) -> DocumentoComercial:
    documento = await db.get(DocumentoComercial, documento_id)
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento comercial no encontrado")
    return documento


@router.get("/plantillas", response_model=list[PlantillaDocumentoOut])
async def list_plantillas(db: AsyncSession = Depends(get_db)):
    """List every template version (active or not) so the UI can show which
    one is live and flag provisional ones clearly."""
    result = await db.execute(
        select(PlantillaDocumento).order_by(PlantillaDocumento.tipo, PlantillaDocumento.version.desc())
    )
    return [_plantilla_out(p) for p in result.scalars().all()]


@router.patch("/plantillas/{plantilla_id}", response_model=PlantillaDocumentoOut)
async def update_plantilla(plantilla_id: int, data: PlantillaDocumentoUpdate, db: AsyncSession = Depends(get_db)):
    """Edit a template's HTML/placeholders in place — this is how Judit's
    real contract text replaces the seeded provisional one, without a
    redeploy or DB console."""
    plantilla = await db.get(PlantillaDocumento, plantilla_id)
    if plantilla is None:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    plantilla.contenido_html = data.contenido_html
    if data.nombre:
        plantilla.nombre = data.nombre
    plantilla.version += 1
    await db.commit()
    await db.refresh(plantilla)
    return _plantilla_out(plantilla)


@router.get("", response_model=list[DocumentoComercialOut])
async def list_documentos(cliente_id: int | None = Query(None), db: AsyncSession = Depends(get_db)):
    statement = select(DocumentoComercial).order_by(DocumentoComercial.created_at.desc())
    if cliente_id is not None:
        statement = statement.where(DocumentoComercial.cliente_id == cliente_id)
    result = await db.execute(statement)
    return [DocumentoComercialOut.model_validate(item) for item in result.scalars().all()]


@router.get("/{documento_id}", response_model=DocumentoComercialOut)
async def get_documento(documento_id: int, db: AsyncSession = Depends(get_db)):
    documento = await _get_or_404(db, documento_id)
    return DocumentoComercialOut.model_validate(documento)


@router.get("/{documento_id}/pdf")
async def download_pdf(documento_id: int, db: AsyncSession = Depends(get_db)):
    documento = await _get_or_404(db, documento_id)
    if not documento.pdf_path or not os.path.exists(documento.pdf_path):
        raise HTTPException(status_code=404, detail="El PDF de este documento no está disponible.")
    filename = f"{documento.tipo}_{documento.numero or documento.id}.pdf"
    return FileResponse(documento.pdf_path, media_type="application/pdf", filename=filename)


@router.post("/{documento_id}/enviar", response_model=DocumentoComercialOut)
async def enviar_documento(documento_id: int, data: EnviarDocumentoRequest, db: AsyncSession = Depends(get_db)):
    """Send the already-generated PDF by email with attachment. Requires
    EMAIL_SENDING_ENABLED=true AND confirmar=true on every call — see
    services/mailer.py. Never sends automatically."""
    documento = await _get_or_404(db, documento_id)
    if not data.confirmar:
        raise HTTPException(status_code=422, detail="Debe confirmar explícitamente el envío (confirmar=true).")
    available, reason = email_sending_available()
    if not available:
        raise HTTPException(status_code=409, detail=reason)
    if not documento.pdf_path or not os.path.exists(documento.pdf_path):
        raise HTTPException(status_code=404, detail="El PDF de este documento no está disponible.")

    cliente = await db.get(Cliente, documento.cliente_id)
    destino = data.email_destino or (cliente.email if cliente else None)
    if not destino:
        raise HTTPException(
            status_code=422,
            detail="No hay email de destino: indíquelo o registre el email del cliente primero.",
        )

    tipo_label = "Contrato" if documento.tipo == "contrato" else "Factura"
    asunto = f"{tipo_label} — {cliente.nombre_razon_social if cliente else documento.cliente_id}"
    html = (
        f"<p>Adjuntamos {tipo_label.lower()} {documento.numero or ''}.</p>"
        f"<p>{data.mensaje or ''}</p>"
    )

    def _leer_y_enviar() -> None:
        with open(documento.pdf_path, "rb") as fh:
            contenido = fh.read()
        adjunto = Adjunto(nombre=os.path.basename(documento.pdf_path), contenido=contenido)
        enviar_email(destino=destino, asunto=asunto, html=html, adjuntos=[adjunto], confirmar=True)

    try:
        await run_in_threadpool(_leer_y_enviar)
    except EmailSendingDisabled as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        documento.estado = "error_envio"
        await db.commit()
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el email: {exc}") from exc

    documento.estado = "enviado"
    documento.email_destino = destino
    documento.enviado_at = datetime.now(timezone.utc)
    db.add(ActividadCliente(
        cliente_id=documento.cliente_id, tipo="email",
        titulo=f"{tipo_label} enviado por email", datos={"destino": destino, "documento_id": documento.id},
    ))
    await db.commit()
    await db.refresh(documento)
    return DocumentoComercialOut.model_validate(documento)
