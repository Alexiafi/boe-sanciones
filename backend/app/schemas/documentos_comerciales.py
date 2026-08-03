from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CampoFaltanteOut(BaseModel):
    campo: str
    mensaje: str


class ValidacionOut(BaseModel):
    listo: bool
    faltantes: list[CampoFaltanteOut]


class DocumentoComercialOut(BaseModel):
    id: int
    cliente_id: int
    tipo: str
    serie: str | None = None
    numero: str | None = None
    estado: str
    email_destino: str | None = None
    enviado_at: datetime | None = None
    created_at: datetime
    datos: dict | None = None

    model_config = {"from_attributes": True}


class ContratoGenerarRequest(BaseModel):
    precio: float = Field(gt=0)


class FacturaGenerarRequest(BaseModel):
    cuantia: float = Field(gt=0)
    concepto: str = Field(min_length=1)


class EnviarDocumentoRequest(BaseModel):
    email_destino: str | None = None
    confirmar: bool = False
    mensaje: str | None = None


class PlantillaDocumentoOut(BaseModel):
    id: int
    tipo: str
    nombre: str
    contenido_html: str
    version: int
    activo: bool
    es_provisional: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PlantillaDocumentoUpdate(BaseModel):
    nombre: str | None = None
    contenido_html: str = Field(min_length=1)
