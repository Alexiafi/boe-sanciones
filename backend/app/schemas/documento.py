from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class BoeDocumentoOut(BaseModel):
    id: int
    boe_id: str
    fecha_publicacion: date
    diario_numero: int | None = None
    seccion_codigo: str | None = None
    seccion_nombre: str | None = None
    departamento_nombre: str | None = None
    epigrafe_nombre: str | None = None
    titulo: str
    familia_sancionadora: str | None = None
    confidence: float | None = None
    url_html: str | None = None
    url_xml: str | None = None
    url_pdf: str | None = None
    created_at: datetime
    sancionados_count: int = 0

    model_config = {"from_attributes": True}


class BoeDocumentoDetail(BoeDocumentoOut):
    texto_plano: str | None = None
    match_rules: dict | None = None
    raw_sumario_item: dict | None = None
