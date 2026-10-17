from __future__ import annotations

from datetime import date, datetime

import re
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


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

    # The party's identity across notices (see services/identidad.py): filled by
    # the endpoints, not ORM attributes.
    nombre_mostrado: str | None = None
    cliente_nombre: str | None = None
    cliente_estado: str | None = None
    otras_notificaciones: int = 0
    # Another notice of the same DNI/CIF was already marked "contactada".
    ya_contactado: bool = False
    ultima_gestion: datetime | None = None
    # How many follow-up notes the party has across all its notices.
    notas_del_titular: int = 0

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


class SancionRelacionadaOut(BaseModel):
    """Another notice of the same DNI/CIF (shown on the detail page so the
    history of the party — and who already called — is one click away)."""

    id: int
    codigo: str
    estado_oportunidad: str
    fecha_publicacion: str | None = None
    organismo_emisor: str | None = None
    expediente: str | None = None
    importe_multa_eur: float | None = None
    importe_deuda_eur: float | None = None
    cliente_id: int | None = None
    ultima_nota: str | None = None


class SancionadoDetail(SancionadoOut):
    seguimientos: list["SeguimientoOut"] = []
    relacionadas: list[SancionRelacionadaOut] = []
    # Notes written on the party's OTHER notices, newest first.
    seguimientos_relacionados: list["SeguimientoRelacionadoOut"] = []


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


class SeguimientoRelacionadoOut(BaseModel):
    id: int
    sancionado_id: int
    codigo: str
    nota: str | None = None
    estado: str
    created_at: datetime


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


def normalise_identificador_fiscal(value: str | None) -> str | None:
    """Strip separators and uppercase a CIF/NIF/DNI/NIE. Empty → None."""
    if value is None:
        return None
    value = re.sub(r"[\s.\-]", "", str(value)).upper()
    if not value:
        return None
    if len(value) > 50:
        raise ValueError("Identificador demasiado largo")
    return value


# Manual edits touch these fields; the PATCH handler uses this set to decide
# whether to (re)mark contacto_estado as "manual" so automatic enrichment never
# overwrites what the user just entered.
CONTACT_FIELDS = frozenset({
    "telefono", "email", "web", "linkedin_url", "telefono_secundario",
    "facebook_url", "instagram_url", "twitter_url",
})


class SancionadoCreate(BaseModel):
    """Alta manual de una multa (y, opcionalmente, del cliente asociado)."""

    model_config = {"extra": "forbid"}

    nombre: str | None = None
    tipo_persona: Literal["fisica", "juridica"] | None = None
    identificador: str | None = None
    tipo_identificador: Literal["CIF", "NIF", "NIE", "DNI"] | None = None
    direccion: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None = None
    telefono: str | None = None
    email: str | None = None
    web: str | None = None
    matricula_coche: str | None = None
    importe_multa_eur: float | None = None
    tipo_infraccion: str | None = None
    razon_sancion: str | None = None
    expediente: str | None = None
    organismo_emisor: str | None = None
    dominio_material: str | None = None
    fecha_publicacion: date | None = None
    observaciones: str | None = None
    titulo_documento: str | None = None
    crear_cliente: bool = False

    @field_validator(
        "nombre", "direccion", "localidad", "provincia", "codigo_postal",
        "matricula_coche", "tipo_infraccion", "razon_sancion", "expediente",
        "organismo_emisor", "dominio_material", "observaciones", "titulo_documento",
        mode="before",
    )
    @classmethod
    def strip_blanks(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("identificador", mode="before")
    @classmethod
    def validate_identificador(cls, value: str | None) -> str | None:
        return normalise_identificador_fiscal(value)

    @field_validator("telefono", mode="before")
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

    @field_validator("web", mode="before")
    @classmethod
    def validate_web(cls, value: str | None) -> str | None:
        return _validate_url_value(value)

    @field_validator("importe_multa_eur")
    @classmethod
    def validate_importe(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("La cuantía no puede ser negativa")
        return value

    @model_validator(mode="after")
    def require_identity(self) -> "SancionadoCreate":
        if not self.nombre and not self.identificador:
            raise ValueError("Indica al menos el nombre/razón social o el CIF/NIF")
        return self


class SancionadoUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    # "cliente" is accepted ONLY as "unchanged" for a notice that already is a
    # client's (the edit form sends the current state back on every save); the
    # endpoint rejects moving any other notice to it.
    estado_oportunidad: Literal["nueva", "revisada", "contactada", "descartada", "cliente"] | None = None
    nombre: str | None = None
    identificador: str | None = None
    tipo_identificador: Literal["CIF", "NIF", "NIE", "DNI"] | None = None
    direccion: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None = None
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

    @field_validator("nombre", "direccion", "localidad", "provincia", "codigo_postal", mode="before")
    @classmethod
    def strip_nombre(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        # Column widths (see models/sancionado.py): an over-long value must be a
        # 422 the form can show, not a database error.
        limite = {"nombre": 500, "localidad": 200, "provincia": 200, "codigo_postal": 10}.get(info.field_name)
        if limite and len(value) > limite:
            raise ValueError(f"No puede superar {limite} caracteres")
        return value or None

    @field_validator("identificador", mode="before")
    @classmethod
    def validate_identificador(cls, value: str | None) -> str | None:
        return normalise_identificador_fiscal(value)

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
    # Filled by the endpoint (not an ORM attribute): the client's display name.
    cliente_nombre: str | None = None
    identificador: str | None = None
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
    # Live progress of a running pipeline (see tasks/scraping._latido).
    fase: str | None = None
    progreso_actual: int | None = None
    progreso_total: int | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScrapingTrigger(BaseModel):
    fecha: str  # YYYY-MM-DD
    force: bool = False
    permitir_extraccion_pago: bool = False
    # "tiempo_real" | "batch"; None follows the runtime configuration.
    modo_extraccion: Literal["tiempo_real", "batch"] | None = None


class ExtraccionBatchItemOut(BaseModel):
    id: int
    custom_id: str
    boe_document_id: int | None = None
    historico_resultado_id: int | None = None
    status: str
    error: str | None = None
    afectados: int = 0

    model_config = {"from_attributes": True}


class ExtraccionBatchOut(BaseModel):
    id: int
    tipo: str
    scraping_run_id: int | None = None
    modelo: str
    status: str
    openai_batch_id: str | None = None
    total_items: int = 0
    completados: int = 0
    errores: int = 0
    sancionados_creados: int = 0
    error_log: str | None = None
    enviado_at: datetime | None = None
    ultimo_check_at: datetime | None = None
    finalizado_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    pages: int
