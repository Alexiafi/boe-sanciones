from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class SancionadoOut(BaseModel):
    id: int
    boe_document_id: int
    nombre: str | None = None
    tipo_persona: str | None = None
    identificador: str | None = None
    tipo_identificador: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    matricula_coche: str | None = None
    importe_multa_eur: float | None = None
    tipo_infraccion: str | None = None
    razon_sancion: str | None = None
    expediente: str | None = None
    estado_publicacion: str | None = None
    plazo_notificacion: str | None = None
    plazo_alegaciones: str | None = None
    plazo_recurso: str | None = None
    base_legal: str | None = None
    organismo_emisor: str | None = None
    dominio_material: str | None = None
    created_at: datetime

    # Denormalized from documento for list views
    boe_id: str | None = None
    fecha_publicacion: str | None = None
    titulo_documento: str | None = None
    url_html: str | None = None
    url_documento: str | None = None

    model_config = {"from_attributes": True}


class SancionadoDetail(SancionadoOut):
    seguimientos: list["SeguimientoOut"] = []


class SeguimientoOut(BaseModel):
    id: int
    sancionado_id: int
    nota: str | None = None
    estado: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SeguimientoCreate(BaseModel):
    nota: str | None = None
    estado: str = "pendiente"


class NotificacionOut(BaseModel):
    id: int
    tipo: str
    titulo: str
    mensaje: str | None = None
    leida: bool
    sancionado_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificacionMarkRead(BaseModel):
    ids: list[int]


class ScrapingRunOut(BaseModel):
    id: int
    fecha_boe: date
    status: str
    total_docs: int | None = None
    candidates: int | None = None
    extracted: int | None = None
    errors: int | None = None
    error_log: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScrapingTrigger(BaseModel):
    fecha: str  # YYYY-MM-DD
    force: bool = False


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int
