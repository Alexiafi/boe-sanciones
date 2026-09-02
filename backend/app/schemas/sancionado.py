from __future__ import annotations

from datetime import date, datetime

import re
from typing import Literal

from pydantic import BaseModel, field_validator


class SancionadoOut(BaseModel):
    id: int
    boe_document_id: int
    codigo: str
    estado_oportunidad: str
    nombre: str | None = None
    tipo_persona: str | None = None
    identificador: str | None = None
    tipo_identificador: str | None = None
    direccion: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None = None
    telefono: str | None = None
    email: str | None = None
    matricula_coche: str | None = None
    importe_multa_eur: float | None = None
    tipo_infraccion: str | None = None
    razon_sancion: str | None = None
    expediente: str | None = None
    estado_publicacion: str | None = None
    tipo_procedimiento: str | None = None
    importe_deuda_eur: float | None = None
    plazo_notificacion: str | None = None
    plazo_alegaciones: str | None = None
    plazo_recurso: str | None = None
    plazo_pago_voluntario: str | None = None
    base_legal: str | None = None
    organismo_emisor: str | None = None
    dominio_material: str | None = None
    fecha_resolucion: date | None = None
    observaciones: str | None = None
    created_at: datetime

    # Contact enrichment (session 2)
    web: str | None = None
    linkedin_url: str | None = None
    telefono_secundario: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    contacto_detalle: dict | None = None
    contacto_estado: str = "pendiente"
    contacto_fuente: str | None = None
    contacto_url: str | None = None
    contacto_confidence: float | None = None
    contacto_actualizado_at: datetime | None = None
    cliente_id: int | None = None

    # Denormalized from documento for list views
    boe_id: str | None = None
    fecha_publicacion: str | None = None
    titulo_documento: str | None = None
    url_html: str | None = None
    url_documento: str | None = None
    # True when the original bytes or at least the extracted plain text are
    # stored locally and can be served even if the BOE removed the document.
    tiene_copia_local: bool = False

    model_config = {"from_attributes": True}


class SancionadoDetail(SancionadoOut):
    seguimientos: list["SeguimientoOut"] = []


class EnriquecimientoIntentoOut(BaseModel):
    id: int
    sancionado_id: int
    proveedor: str
    consulta: str | None = None
    resultado: str
    url_origen: str | None = None
    confidence: float | None = None
    evidencia: str | None = None
    coste_estimado_eur: float | None = None
    duracion_ms: int | None = None
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EnriquecimientoLoteRequest(BaseModel):
    confirmar: bool = False
    limite: int | None = None
    fecha_desde: date | None = None
    fecha_hasta: date | None = None


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


def _validate_phone_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 50 or not re.fullmatch(r"[0-9+()./ -]+", value):
        raise ValueError("Teléfono no válido")
    return value


def _validate_url_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 500 or not re.match(r"^https?://", value):
        raise ValueError("URL no válida (debe comenzar por http:// o https://)")
    return value


# Manual edits touch these fields; the PATCH handler uses this set to decide
# whether to (re)mark contacto_estado as "manual" so automatic enrichment never
# overwrites what the user just entered.
CONTACT_FIELDS = frozenset({
    "telefono", "email", "web", "linkedin_url", "telefono_secundario",
    "facebook_url", "instagram_url", "twitter_url",
})


class SancionadoUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    estado_oportunidad: Literal["nueva", "revisada", "contactada", "descartada"] | None = None
    telefono: str | None = None
    email: str | None = None
    web: str | None = None
    linkedin_url: str | None = None
    telefono_secundario: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None

    @field_validator("estado_oportunidad", mode="before")
    @classmethod
    def reject_null_estado(cls, value: str | None) -> str | None:
        # `null` is a valid way to clear telefono/email, but estado_oportunidad is
        # NOT NULL in the database; an explicit null here must be a 422, not a 500
        # IntegrityError from the ORM commit.
        if value is None:
            raise ValueError("estado_oportunidad no puede ser null")
        return value

    @field_validator("telefono", "telefono_secundario", mode="before")
    @classmethod
    def validate_telefono(cls, value: str | None) -> str | None:
        return _validate_phone_value(value)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 200 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Email no válido")
        return value

    @field_validator("web", "linkedin_url", "facebook_url", "instagram_url", "twitter_url", mode="before")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return _validate_url_value(value)


class NotificacionOut(BaseModel):
    id: int
    tipo: str
    titulo: str
    mensaje: str | None = None
    leida: bool
    sancionado_id: int | None = None
    cliente_id: int | None = None
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
    extraction_requested: bool = False
    extraction_provider: str | None = None
    extraction_limit: int | None = None
    extraction_attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScrapingTrigger(BaseModel):
    fecha: str  # YYYY-MM-DD
    force: bool = False
    permitir_extraccion_pago: bool = False


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int
