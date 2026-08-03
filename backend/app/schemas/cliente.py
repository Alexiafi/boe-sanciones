from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class ClienteOut(BaseModel):
    id: int
    codigo: str
    nombre_razon_social: str
    tipo_persona: str | None = None
    cif_nif: str | None = None
    dni_nie: str | None = None
    matriculas: list[str] = []
    persona_contacto: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion_fiscal: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None = None
    web: str | None = None
    sector: str | None = None
    estado_cliente: str
    fecha_contrato: date | None = None
    precio_contrato: float | None = None
    sancion_origen_id: int
    created_at: datetime

    # Never stored, always computed at read time (see services/clientes.deuda_pendiente_eur).
    deuda_pendiente_eur: float = 0.0

    model_config = {"from_attributes": True}


class SancionVinculadaOut(BaseModel):
    """Minimal opportunity view embedded in a client's ficha — enough to link
    back to the source sanction without duplicating the full SancionadoOut."""

    id: int
    codigo: str
    fecha_publicacion: str | None = None
    tipo_infraccion: str | None = None
    importe_multa_eur: float | None = None
    importe_deuda_eur: float | None = None
    url_documento: str | None = None

    model_config = {"from_attributes": True}


class NotaClienteOut(BaseModel):
    id: int
    cliente_id: int
    texto: str
    autor: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotaClienteCreate(BaseModel):
    texto: str
    autor: str | None = None

    @field_validator("texto")
    @classmethod
    def texto_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El texto de la nota no puede estar vacío")
        return value


class ActividadClienteOut(BaseModel):
    id: int
    cliente_id: int
    tipo: str
    titulo: str
    detalle: str | None = None
    datos: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccionAgendadaOut(BaseModel):
    id: int
    cliente_id: int
    tipo: str
    titulo: str
    fecha_programada: datetime | None = None
    estado: str
    notas: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccionAgendadaCreate(BaseModel):
    tipo: Literal["llamada", "email", "tarea"]
    titulo: str
    fecha_programada: datetime | None = None
    notas: str | None = None

    @field_validator("titulo")
    @classmethod
    def titulo_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El título de la acción no puede estar vacío")
        return value


class AccionAgendadaUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    estado: Literal["pendiente", "hecha", "cancelada"] | None = None
    notas: str | None = None


class ClienteDetail(ClienteOut):
    sanciones: list[SancionVinculadaOut] = []
    notas: list[NotaClienteOut] = []
    actividades: list[ActividadClienteOut] = []
    acciones: list[AccionAgendadaOut] = []


class ClienteUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    estado_cliente: Literal["activo", "inactivo"] | None = None
    persona_contacto: str | None = None
    telefono: str | None = None
    email: str | None = None
    web: str | None = None
    sector: str | None = None
    direccion_fiscal: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None = None
    fecha_contrato: date | None = None
    precio_contrato: float | None = None

    @field_validator("estado_cliente", mode="before")
    @classmethod
    def reject_null_estado(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("estado_cliente no puede ser null")
        return value

    @field_validator("telefono", mode="before")
    @classmethod
    def validate_telefono(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 50 or not re.fullmatch(r"[0-9+()./ -]+", value):
            raise ValueError("Teléfono no válido")
        return value

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
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 500 or not re.match(r"^https?://", value):
            raise ValueError("URL no válida (debe comenzar por http:// o https://)")
        return value
