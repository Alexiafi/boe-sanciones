from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class HistoricoResultadoOut(BaseModel):
    id: int
    cliente_id: int
    historico_doc_id: int
    vinculo_id: int | None = None
    score: float
    via_match: str
    estado: str
    extraido: bool
    datos_extraidos: dict | None = None
    created_at: datetime

    # Flattened from the joined HistoricoDoc so the frontend doesn't need a
    # second round trip to show the document itself.
    boe_id: str | None = None
    fuente: str | None = None
    fecha_publicacion: date | None = None
    titulo: str | None = None
    url_pdf: str | None = None
    url_html: str | None = None
    url_xml: str | None = None
    fuera_de_ventana_teu: bool = False
    # Vínculo's nombre when vinculo_id is set, otherwise the client's own name.
    titular: str | None = None

    model_config = {"from_attributes": True}


class ConsultaItemOut(BaseModel):
    historico_doc_id: int
    boe_id: str
    fuente: str
    fecha_publicacion: date
    titulo: str
    via_match: str
    score: float
    url_pdf: str | None = None
    url_html: str | None = None
    url_xml: str | None = None
    fuera_de_ventana_teu: bool = False


class CoberturaTeuOut(BaseModel):
    ventana_publica_desde: str
    consulta_en_vivo: bool
    motivo_sin_consulta: str | None = None


class ConsultaRequest(BaseModel):
    cif: str | None = None
    dni: str | None = None
    matricula: str | None = None
    nombre: str | None = None
    incluir_teu: bool = False

    @model_validator(mode="after")
    def _al_menos_un_criterio(self) -> "ConsultaRequest":
        if not any([self.cif, self.dni, self.matricula, self.nombre]):
            raise ValueError("Debe indicar al menos un criterio: cif, dni, matricula o nombre.")
        return self


class ConsultaResponse(BaseModel):
    resultados: list[ConsultaItemOut]
    avisos: list[str]
    cobertura_teu: CoberturaTeuOut


class ClienteHistoricoBuscarRequest(BaseModel):
    incluir_teu: bool = False


class ClienteHistoricoBuscarResponse(BaseModel):
    resultados: list[HistoricoResultadoOut]
    avisos: list[str]
    cobertura_teu: CoberturaTeuOut


class HistoricoExtraerRequest(BaseModel):
    resultado_ids: list[int] = Field(min_length=1)
    confirmar: bool = False
    permitir_extraccion_pago: bool = False
    force: bool = False


class BackfillPlanRequest(BaseModel):
    fecha_desde: date
    fecha_hasta: date

    @model_validator(mode="after")
    def _rango_valido(self) -> "BackfillPlanRequest":
        if self.fecha_desde > self.fecha_hasta:
            raise ValueError("fecha_desde no puede ser posterior a fecha_hasta.")
        return self


class BackfillPlanOut(BaseModel):
    fecha_desde: date
    fecha_hasta: date
    dias: int
    documentos_estimados: int
    candidatos_estimados: int
    max_dias_por_ejecucion: int
    max_documentos_por_ejecucion: int
    ejecuciones_estimadas: int
    token: str
    aviso: str


class BackfillRequest(BaseModel):
    fecha_desde: date
    fecha_hasta: date
    confirmar: bool = False
    confirmacion: str = ""
    max_dias: int | None = None
    max_documentos: int | None = None


class BackfillRunOut(BaseModel):
    id: int
    fecha_desde: date
    fecha_hasta: date
    cursor_fecha: date | None = None
    ultima_fecha_completada: date | None = None
    status: str
    dias_totales: int
    dias_procesados: int
    docs_vistos: int
    docs_candidatos: int
    docs_indexados: int
    errores: int
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class HistoricoCoberturaOut(BaseModel):
    boe_desde: date | None = None
    boe_hasta: date | None = None
    boe_dias_indexados: int
    teu_desde: date | None = None
    teu_hasta: date | None = None
    teu_dias_indexados: int
    total_documentos: int
    ventana_publica_teu_desde: str
