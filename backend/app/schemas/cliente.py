from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


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
    vinculo_id: int | None = None
    # Not an ORM attribute — set by the endpoint after model_validate() to the
    # vínculo's nombre, or the client's own name when vinculo_id is null. Lets
    # the UI group "Sanciones vinculadas" by titular without a second call.
    titular: str | None = None

    model_config = {"from_attributes": True}


class VinculoOut(BaseModel):
    id: int
    cliente_id: int
    cliente_vinculado_id: int | None = None
    rol: str
    nombre: str | None = None
    tipo_persona: str | None = None
    identificador: str | None = None
    tipo_identificador: str | None = None
    telefono: str | None = None
    email: str | None = None
    notas: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


def _validate_vinculo_telefono(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 50 or not re.fullmatch(r"[0-9+()./ -]+", value):
        raise ValueError("Teléfono no válido")
    return value


def _validate_vinculo_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 200 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("Email no válido")
    return value


class VinculoCreate(BaseModel):
    cliente_vinculado_id: int | None = None
    rol: str
    nombre: str | None = None
    tipo_persona: Literal["fisica", "juridica"] | None = None
    identificador: str | None = None
    tipo_identificador: str | None = None
    telefono: str | None = None
    email: str | None = None
    notas: str | None = None

    @field_validator("rol")
    @classmethod
    def rol_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El rol no puede estar vacío")
        return value

    @field_validator("telefono", mode="before")
    @classmethod
    def validate_telefono(cls, value: str | None) -> str | None:
        return _validate_vinculo_telefono(value)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _validate_vinculo_email(value)

    @model_validator(mode="after")
    def _nombre_o_vinculado(self) -> "VinculoCreate":
        if not self.nombre and not self.cliente_vinculado_id:
            raise ValueError("Debe indicar un nombre o un cliente_vinculado_id ya existente")
        return self


class VinculoUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    cliente_vinculado_id: int | None = None
    rol: str | None = None
    nombre: str | None = None
    tipo_persona: Literal["fisica", "juridica"] | None = None
    identificador: str | None = None
    tipo_identificador: str | None = None
    telefono: str | None = None
    email: str | None = None
    notas: str | None = None

    @field_validator("rol", mode="before")
    @classmethod
    def reject_null_rol(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("rol no puede ser null")
        value = value.strip()
        if not value:
            raise ValueError("El rol no puede estar vacío")
        return value

    @field_validator("telefono", mode="before")
    @classmethod
    def validate_telefono(cls, value: str | None) -> str | None:
        return _validate_vinculo_telefono(value)

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _validate_vinculo_email(value)


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
    vinculos: list[VinculoOut] = []


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
