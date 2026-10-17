"""Structured extraction of sanction/embargo/debt data using OpenAI structured outputs."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from openai import BadRequestError, OpenAI
from openai.lib._parsing import type_to_response_format_param
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

DATOS DE CONTACTO:
- `telefono` y `email`: devuélvelos SIEMPRE como null. En estos documentos el único teléfono o email \
que aparece es el de la Administración que publica (atención al ciudadano, recaudación, juzgado, \
sede electrónica), nunca el de la persona afectada; sus datos de contacto se obtienen por otra vía.
- `direccion`, `localidad`, `provincia`, `codigo_postal`: solo los de la propia persona o entidad \
afectada (su domicilio). NUNCA la dirección del organismo, de sus oficinas o de un juzgado.
- Un edicto del Tablón Edictal Único identifica a la persona solo por su DNI/NIF/CIF: \
en ese caso `nombre` es null. No inventes nombres ni uses el de funcionarios o firmantes.

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
    fecha_resolucion: date | None = None
    observaciones: str | None = None


class ResultadoExtraccion(BaseModel):
    afectados: list[AfectadoExtraido]
    resumen: str | None = None
    es_documento_relevante: bool = True


# Keep old name for backwards compatibility with scraping.py
SancionadoExtraido = AfectadoExtraido


def _resultado_vacio() -> ResultadoExtraccion:
    return ResultadoExtraccion(afectados=[], resumen=None, es_documento_relevante=False)


def _admite_temperature(model: str) -> bool:
    """Reasoning-class models (gpt-5 family, o-series) reject any
    ``temperature`` other than the default; sending it makes the whole
    request fail with a 400, so it is only included where it is accepted."""
    lowered = model.lower()
    return not (lowered.startswith("gpt-5") or lowered.startswith("o1") or lowered.startswith("o3") or lowered.startswith("o4"))


# Flipped on the first time the API rejects ``reasoning_effort`` for the
# configured model: from then on this process stops sending it instead of
# failing every document (a typo in .env must not stop the whole pipeline).
_REASONING_EFFORT_RECHAZADO = False


def _reasoning_effort_activo() -> bool:
    return bool((settings.openai_reasoning_effort or "").strip()) and not _REASONING_EFFORT_RECHAZADO


def build_extraction_request(text: str, titulo: str = "", *, model: str | None = None) -> dict[str, Any]:
    """The exact ``/v1/chat/completions`` body used for one document.

    Shared verbatim by the real-time path (``extract_sanctions``) and the
    Batch API path (``services/openai_batch.py``), so both modes produce the
    same structured output for the same document — the only difference is
    price and latency.
    """
    model = model or settings.openai_model
    truncated = text[:MAX_TEXT_CHARS]
    user_msg = (
        f"TÍTULO DEL DOCUMENTO BOE:\n{titulo}\n\n"
        f"TEXTO DEL DOCUMENTO:\n{truncated}"
    )
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "response_format": type_to_response_format_param(ResultadoExtraccion),
    }
    if _admite_temperature(model):
        body["temperature"] = 0.0
    elif _reasoning_effort_activo():
        body["reasoning_effort"] = settings.openai_reasoning_effort.strip()
    return body


def parse_extraction_response(body: dict[str, Any]) -> ResultadoExtraccion:
    """Turn a raw chat-completion response body (real-time or one batch
    output line) into ``ResultadoExtraccion``. Raises on a refusal or on
    content that does not match the schema — callers decide whether that is
    a per-document error (it is) rather than silently returning nothing."""
    choices = body.get("choices") or []
    if not choices:
        raise ValueError("Respuesta de OpenAI sin 'choices'")
    message = choices[0].get("message") or {}
    if message.get("refusal"):
        raise ValueError(f"OpenAI rechazó la petición: {message['refusal']}")
    content = message.get("content")
    if not content:
        raise ValueError("Respuesta de OpenAI sin contenido")
    return ResultadoExtraccion.model_validate_json(content)


def _es_rechazo_de_reasoning_effort(exc: Exception) -> bool:
    return isinstance(exc, BadRequestError) and "reasoning" in str(exc).lower()


def extract_sanctions(text: str, titulo: str = "") -> ResultadoExtraccion:
    """
    Use OpenAI structured outputs to extract affected entities from BOE text.
    Real-time path: one synchronous call per document (the pipeline runs several
    of them at once, see ``tasks/scraping.py``). Raises on API errors so the
    pipeline records the document as ``error`` (and can retry it on a later
    run) instead of marking it completed with zero affected parties.
    """
    global _REASONING_EFFORT_RECHAZADO
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key configured, skipping extraction")
        return _resultado_vacio()

    # max_retries covers 429/5xx/timeouts with exponential backoff: several
    # documents are in flight at once, so the occasional rate limit is normal.
    client = OpenAI(api_key=settings.openai_api_key, max_retries=6, timeout=settings.openai_timeout_s)
    try:
        completion = client.chat.completions.create(**build_extraction_request(text, titulo))
    except Exception as exc:
        if not _es_rechazo_de_reasoning_effort(exc):
            raise
        logger.warning("OpenAI rechazó reasoning_effort para %s; se envía sin él: %s", settings.openai_model, exc)
        _REASONING_EFFORT_RECHAZADO = True
        completion = client.chat.completions.create(**build_extraction_request(text, titulo))
    result = parse_extraction_response(completion.model_dump(mode="json"))
    logger.info(
        "Extracted %d affected entities (relevant=%s)",
        len(result.afectados), result.es_documento_relevante,
    )
    return result
