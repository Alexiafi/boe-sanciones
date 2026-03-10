"""Structured extraction of sanction/embargo/debt data using OpenAI structured outputs."""

from __future__ import annotations

import logging
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 30_000

SYSTEM_PROMPT = """\
Eres un experto jurista especializado en derecho administrativo sancionador español, \
procedimientos de embargo, deudas públicas y ejecuciones patrimoniales publicadas en el \
Boletín Oficial del Estado (BOE).

Tu tarea es extraer TODAS las personas físicas y jurídicas que aparezcan como:
- Sancionados en expedientes sancionadores
- Deudores en procedimientos de apremio o cobro de deudas
- Personas o entidades sujetas a embargo de bienes
- Personas requeridas de pago por deudas tributarias o de Seguridad Social
- Infractores de cualquier normativa administrativa
- Personas notificadas en edictos judiciales de cobro o ejecución
- Cualquier persona o entidad contra la que se dirija una acción coercitiva o punitiva del Estado

NO extraigas:
- Funcionarios, directores o firmantes de convenios (son autoridades, no sancionados)
- Partes de convenios de colaboración o formación profesional
- Cargos institucionales mencionados como emisores de la resolución
- Testigos, peritos o terceros que no sean objeto de la acción

Para CADA persona o entidad afectada, extrae toda la información disponible.
Si un campo no aparece explícitamente en el texto, devuelve null.
Si un identificador (DNI/NIF/CIF) está parcialmente oculto con asteriscos (***), \
extráelo tal cual aparece.

IMPORTANTE: Si el documento es un convenio de formación, acuerdo de colaboración, \
nombramiento, o cualquier documento que NO contenga sanciones, embargos ni deudas, \
devuelve una lista vacía de afectados.
"""


class AfectadoExtraido(BaseModel):
    nombre: str | None = None
    tipo_persona: Literal["fisica", "juridica"] | None = None
    identificador: str | None = None
    tipo_identificador: Literal["CIF", "NIF", "NIE", "DNI", "pasaporte", "otro"] | None = None
    direccion: str | None = None
    localidad: str | None = None
    provincia: str | None = None
    codigo_postal: str | None = None
    telefono: str | None = None
    email: str | None = None
    matricula_coche: str | None = None

    tipo_procedimiento: Literal[
        "sancion", "embargo", "apremio", "deuda",
        "requerimiento_pago", "ejecucion", "otro",
    ] | None = None
    importe_multa_eur: float | None = None
    importe_deuda_eur: float | None = None
    tipo_infraccion: Literal["leve", "grave", "muy_grave"] | None = None
    razon_sancion: str | None = None
    expediente: str | None = None

    estado_publicacion: Literal[
        "incoacion", "propuesta", "notificacion",
        "resolucion", "sancion_firme", "revocacion",
        "providencia_apremio", "diligencia_embargo",
        "requerimiento_pago", "liquidacion", "desconocido",
    ] | None = None

    plazo_notificacion: str | None = None
    plazo_alegaciones: str | None = None
    plazo_recurso: str | None = None
    plazo_pago_voluntario: str | None = None
    base_legal: str | None = None
    organismo_emisor: str | None = None
    dominio_material: str | None = None
    fecha_resolucion: str | None = None
    observaciones: str | None = None


class ResultadoExtraccion(BaseModel):
    afectados: list[AfectadoExtraido]
    resumen: str | None = None
    es_documento_relevante: bool = True


# Keep old name for backwards compatibility with scraping.py
SancionadoExtraido = AfectadoExtraido


def extract_sanctions(text: str, titulo: str = "") -> ResultadoExtraccion:
    """
    Use OpenAI structured outputs to extract affected entities from BOE text.
    Falls back to an empty result on error.
    """
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key configured, skipping extraction")
        return ResultadoExtraccion(afectados=[], resumen=None, es_documento_relevante=False)

    truncated = text[:MAX_TEXT_CHARS]
    user_msg = (
        f"TÍTULO DEL DOCUMENTO BOE:\n{titulo}\n\n"
        f"TEXTO DEL DOCUMENTO:\n{truncated}"
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        completion = client.beta.chat.completions.parse(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format=ResultadoExtraccion,
            temperature=0.0,
        )
        result = completion.choices[0].message.parsed
        if result is None:
            logger.warning("OpenAI returned unparseable response")
            return ResultadoExtraccion(afectados=[], resumen=None, es_documento_relevante=False)

        logger.info(
            "Extracted %d affected entities (relevant=%s)",
            len(result.afectados), result.es_documento_relevante,
        )
        return result

    except Exception:
        logger.exception("OpenAI extraction failed")
        return ResultadoExtraccion(afectados=[], resumen=None, es_documento_relevante=False)
