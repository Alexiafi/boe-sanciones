"""OpenAI Batch API transport for structured extraction.

The Batch API takes a JSONL file where every line is one ordinary
``/v1/chat/completions`` request tagged with a ``custom_id``, processes it
asynchronously (up to 24h, in practice usually much less) at roughly half
the real-time price, and returns another JSONL file with one response per
line. This module only knows how to build, submit, poll and read those
files; deciding *what* to do with each result lives in
``tasks/extraccion_batch.py`` so the exact same code applies a batch result
as would have applied a real-time one.

Every request body comes from ``services/extractor.build_extraction_request``
— the two modes are guaranteed to send the same prompt, schema and model.

Tests never touch the network: they pass a fake ``BatchTransport``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.config import settings
from app.models.extraccion_batch import ExtraccionBatch, ExtraccionBatchItem
from app.services.extractor import build_extraction_request

logger = logging.getLogger(__name__)

ENDPOINT = "/v1/chat/completions"
COMPLETION_WINDOW = "24h"

# OpenAI statuses -> ours. "validating"/"in_progress"/"finalizing"/"cancelling"
# are all "still working" from the operator's point of view.
_STATUS_MAP = {
    "validating": "en_progreso",
    "in_progress": "en_progreso",
    "finalizing": "en_progreso",
    "cancelling": "en_progreso",
    "completed": "completado",
    "failed": "fallido",
    "expired": "expirado",
    "cancelled": "cancelado",
}
ESTADOS_TERMINALES = {"completado", "fallido", "expirado", "cancelado"}


@dataclass(frozen=True)
class PeticionBatch:
    """One document to include in a batch."""

    custom_id: str
    texto: str
    titulo: str
    boe_document_id: int | None = None
    historico_resultado_id: int | None = None


@dataclass(frozen=True)
class EstadoBatchRemoto:
    status: str  # our vocabulary (see _STATUS_MAP)
    output_file_id: str | None = None
    error_file_id: str | None = None
    completados: int = 0
    fallidos: int = 0
    total: int = 0
    detalle_error: str | None = None


@dataclass
class ResultadoLinea:
    custom_id: str
    body: dict[str, Any] | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BatchTransport(Protocol):
    def subir_jsonl(self, contenido: bytes, nombre: str) -> str: ...
    def crear_batch(self, input_file_id: str, metadata: dict[str, str]) -> tuple[str, EstadoBatchRemoto]: ...
    def consultar(self, batch_id: str) -> EstadoBatchRemoto: ...
    def descargar(self, file_id: str) -> str: ...


class OpenAIBatchTransport:
    """Real transport over the official SDK. Built lazily so importing this
    module never constructs a client (tests assert that discipline)."""

    def __init__(self, api_key: str | None = None) -> None:
        # Resolved through services/extractor so the test suite's single
        # "no real OpenAI client" trap (tests/conftest.py) covers this
        # transport too; imported lazily, see class docstring.
        from app.services import extractor as extractor_module

        self._client = extractor_module.OpenAI(api_key=api_key or settings.openai_api_key)

    def subir_jsonl(self, contenido: bytes, nombre: str) -> str:
        archivo = self._client.files.create(file=(nombre, contenido), purpose="batch")
        return archivo.id

    def crear_batch(self, input_file_id: str, metadata: dict[str, str]) -> tuple[str, EstadoBatchRemoto]:
        batch = self._client.batches.create(
            input_file_id=input_file_id, endpoint=ENDPOINT, completion_window=COMPLETION_WINDOW, metadata=metadata,
        )
        return batch.id, _estado_desde_sdk(batch)

    def consultar(self, batch_id: str) -> EstadoBatchRemoto:
        return _estado_desde_sdk(self._client.batches.retrieve(batch_id))

    def descargar(self, file_id: str) -> str:
        return self._client.files.content(file_id).text


def _estado_desde_sdk(batch: Any) -> EstadoBatchRemoto:
    counts = getattr(batch, "request_counts", None)
    errores = getattr(batch, "errors", None)
    detalle = None
    if errores is not None:
        data = getattr(errores, "data", None) or []
        detalle = "; ".join(f"{getattr(e, 'code', '')}: {getattr(e, 'message', '')}" for e in data) or None
    return EstadoBatchRemoto(
        status=_STATUS_MAP.get(getattr(batch, "status", ""), "en_progreso"),
        output_file_id=getattr(batch, "output_file_id", None),
        error_file_id=getattr(batch, "error_file_id", None),
        completados=int(getattr(counts, "completed", 0) or 0),
        fallidos=int(getattr(counts, "failed", 0) or 0),
        total=int(getattr(counts, "total", 0) or 0),
        detalle_error=detalle,
    )


def get_transport() -> BatchTransport:
    return OpenAIBatchTransport()


def construir_jsonl(peticiones: list[PeticionBatch], *, model: str | None = None) -> bytes:
    lineas = []
    for peticion in peticiones:
        linea = {
            "custom_id": peticion.custom_id,
            "method": "POST",
            "url": ENDPOINT,
            "body": build_extraction_request(peticion.texto, peticion.titulo, model=model),
        }
        lineas.append(json.dumps(linea, ensure_ascii=False))
    return ("\n".join(lineas) + "\n").encode("utf-8")


def parsear_salida(contenido: str) -> dict[str, ResultadoLinea]:
    """Index a batch output (or error) JSONL by ``custom_id``."""
    resultados: dict[str, ResultadoLinea] = {}
    for raw_line in contenido.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError:
            logger.warning("Línea de salida de batch ilegible: %.120s", raw_line)
            continue
        custom_id = data.get("custom_id")
        if not custom_id:
            continue
        error = data.get("error")
        response = data.get("response") or {}
        status_code = response.get("status_code")
        body = response.get("body")
        if error:
            mensaje = error.get("message") if isinstance(error, dict) else str(error)
            resultados[custom_id] = ResultadoLinea(custom_id=custom_id, error=mensaje or "error", raw=data)
        elif status_code and int(status_code) != 200:
            mensaje = None
            if isinstance(body, dict):
                mensaje = (body.get("error") or {}).get("message")
            resultados[custom_id] = ResultadoLinea(
                custom_id=custom_id, error=mensaje or f"HTTP {status_code}", raw=data,
            )
        else:
            resultados[custom_id] = ResultadoLinea(custom_id=custom_id, body=body, raw=data)
    return resultados


def enviar_batch(
    db: Session,
    *,
    tipo: str,
    peticiones: list[PeticionBatch],
    transport: BatchTransport,
    scraping_run_id: int | None = None,
    model: str | None = None,
) -> ExtraccionBatch:
    """Persist the batch row + items, upload the JSONL and submit it.

    The row is written with status ``preparando`` *before* any network call
    and flipped to ``enviado`` only after OpenAI accepted it, so a crash in
    between leaves a visible, diagnosable row rather than silent loss. A
    transport failure marks the row ``fallido`` and re-raises so the caller
    can mark its documents accordingly.
    """
    if not peticiones:
        raise ValueError("Un batch necesita al menos una petición")
    model = model or settings.openai_model
    batch = ExtraccionBatch(
        tipo=tipo, scraping_run_id=scraping_run_id, modelo=model, status="preparando",
        total_items=len(peticiones),
    )
    db.add(batch)
    db.flush()
    for peticion in peticiones:
        db.add(ExtraccionBatchItem(
            batch_id=batch.id, custom_id=peticion.custom_id, boe_document_id=peticion.boe_document_id,
            historico_resultado_id=peticion.historico_resultado_id, status="pendiente",
        ))
    db.flush()

    try:
        nombre = f"boe-sanciones-{tipo}-{batch.id}.jsonl"
        batch.input_file_id = transport.subir_jsonl(construir_jsonl(peticiones, model=model), nombre)
        batch_id, estado = transport.crear_batch(
            batch.input_file_id, {"tipo": tipo, "batch_local_id": str(batch.id)},
        )
    except Exception as exc:
        batch.status = "fallido"
        batch.error_log = f"No se pudo enviar el batch a OpenAI: {exc}"[:4_000]
        batch.finalizado_at = datetime.now(timezone.utc)
        db.flush()
        raise

    batch.openai_batch_id = batch_id
    batch.status = estado.status if estado.status in ESTADOS_TERMINALES else "enviado"
    batch.enviado_at = datetime.now(timezone.utc)
    batch.ultimo_check_at = batch.enviado_at
    db.flush()
    logger.info("Batch OpenAI %s enviado (%s, %d peticiones)", batch_id, tipo, len(peticiones))
    return batch
