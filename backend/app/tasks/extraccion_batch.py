"""Poll OpenAI Batch API jobs and apply their results.

Scheduled every few minutes by Celery beat (see ``app/celery_app.py``). For
every ``ExtraccionBatch`` not yet in a terminal state it asks OpenAI for the
status; once a job is ``completed`` (or ``expired``/``failed`` with partial
output) it downloads the JSONL and applies each line through *exactly* the
same code the real-time path uses:

- daily batches (``tipo="diario"``): ``tasks/scraping.aplicar_resultado_documento``
  → opportunities, in-app notification, auto-assignment to existing clients,
  email digest;
- historical batches (``tipo="historico_cliente"``): the same update
  ``tasks/historico_extraccion`` makes on a ``HistoricoResultado``.

Idempotent per item: an item is applied once (``status`` flips to
``completado``/``error``), and ``upsert_afectado`` is itself idempotent, so
re-processing a batch after a crash cannot duplicate opportunities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from app.celery_app import celery
from app.config import settings
from app.database import SyncSessionLocal
from app.models.cliente import ActividadCliente
from app.models.documento import BoeDocumento
from app.models.extraccion_batch import ExtraccionBatch, ExtraccionBatchItem
from app.models.historico import HistoricoResultado
from app.services.extractor import ResultadoExtraccion, parse_extraction_response
from app.services.identidad import ResolverIdentidad
from app.services.notifier import create_inapp_notification, send_email_digest
from app.services.openai_batch import (
    ESTADOS_TERMINALES,
    BatchTransport,
    EstadoBatchRemoto,
    ResultadoLinea,
    get_transport,
    parsear_salida,
)
from app.tasks.scraping import aplicar_resultado_documento, asignar_sanciones_a_clientes

logger = logging.getLogger(__name__)

ESTADOS_ABIERTOS = ("enviado", "en_progreso")


@dataclass(frozen=True)
class BatchDependencies:
    transport: Callable[[], BatchTransport] = get_transport
    notify: Callable[[Any, Any], None] = create_inapp_notification
    send_digest: Callable[[list, str], None] = send_email_digest


def _descargar_resultados(transport: BatchTransport, estado: EstadoBatchRemoto) -> dict[str, ResultadoLinea]:
    resultados: dict[str, ResultadoLinea] = {}
    # The error file (per-request failures) is read first so a custom_id that
    # somehow appears in both is resolved by the successful output line.
    if estado.error_file_id:
        try:
            resultados.update(parsear_salida(transport.descargar(estado.error_file_id)))
        except Exception:
            logger.exception("No se pudo descargar el fichero de errores %s", estado.error_file_id)
    if estado.output_file_id:
        resultados.update(parsear_salida(transport.descargar(estado.output_file_id)))
    return resultados


def _aplicar_item_diario(
    db, item: ExtraccionBatchItem, linea: ResultadoLinea | None, estado_batch: str, deps: BatchDependencies,
    new_sancionados: list, stats: dict[str, int], resolver: ResolverIdentidad | None = None,
) -> None:
    document = db.get(BoeDocumento, item.boe_document_id) if item.boe_document_id else None
    if document is None:
        item.status = "error"
        item.error = "Documento ya no existe"
        return
    document.extraction_attempted_at = datetime.now(timezone.utc)
    document.extractor_version = f"openai-batch:{settings.openai_model}"
    try:
        if linea is None:
            raise ValueError(f"Sin respuesta en la salida del batch (estado {estado_batch})")
        if linea.error or linea.body is None:
            raise ValueError(linea.error or "Respuesta vacía")
        result: ResultadoExtraccion = parse_extraction_response(linea.body)
        item.afectados = aplicar_resultado_documento(
            db, document, result, deps.notify, new_sancionados, stats, resolver=resolver,
        )
        item.status = "completado"
        item.error = None
    except Exception as exc:
        item.status = "error"
        item.error = str(exc)[:2_000]
        document.extraction_status = "error"
        document.extraction_error = str(exc)[:2_000]
        stats["errors"] += 1
        logger.warning("Item %s del batch falló: %s", item.custom_id, exc)


def _aplicar_item_historico(
    db, item: ExtraccionBatchItem, linea: ResultadoLinea | None, estado_batch: str, stats: dict[str, int],
) -> None:
    resultado = db.get(HistoricoResultado, item.historico_resultado_id) if item.historico_resultado_id else None
    if resultado is None:
        item.status = "error"
        item.error = "Resultado histórico ya no existe"
        return
    try:
        if linea is None:
            raise ValueError(f"Sin respuesta en la salida del batch (estado {estado_batch})")
        if linea.error or linea.body is None:
            raise ValueError(linea.error or "Respuesta vacía")
        extraido: ResultadoExtraccion = parse_extraction_response(linea.body)
        resultado.datos_extraidos = extraido.model_dump(mode="json")
        resultado.extraido = True
        resultado.extraido_at = datetime.now(timezone.utc)
        resultado.extractor_version = f"openai-batch:{settings.openai_model}"
        resultado.extraccion_error = None
        doc = resultado.documento
        db.add(ActividadCliente(
            cliente_id=resultado.cliente_id, tipo="sistema",
            titulo=f"Extracción histórica (batch): {doc.titulo[:200]}",
            datos={"historico_resultado_id": resultado.id, "historico_doc_id": doc.id},
        ))
        item.afectados = len(extraido.afectados)
        item.status = "completado"
        item.error = None
        stats["extracted"] += 1
    except Exception as exc:
        item.status = "error"
        item.error = str(exc)[:2_000]
        resultado.extraccion_error = str(exc)[:2_000]
        stats["errors"] += 1
        logger.warning("Item histórico %s del batch falló: %s", item.custom_id, exc)


def aplicar_batch(db, batch: ExtraccionBatch, estado: EstadoBatchRemoto, transport: BatchTransport, deps: BatchDependencies) -> dict[str, int]:
    """Apply a terminal batch. Called once per batch; items already applied
    (a previous partial pass) are skipped."""
    stats = {"extracted": 0, "errors": 0, "clientes_asignados": 0}
    resultados: dict[str, ResultadoLinea] = {}
    try:
        resultados = _descargar_resultados(transport, estado)
    except Exception as exc:
        # Output unreachable: every pending item becomes an error, the batch
        # is still closed so the poller stops retrying forever.
        logger.exception("No se pudo descargar la salida del batch %s", batch.openai_batch_id)
        batch.error_log = f"No se pudo descargar la salida: {exc}"[:4_000]

    new_sancionados: list = []
    fecha_ref = None
    resolver = ResolverIdentidad(db)
    for item in batch.items:
        if item.status != "pendiente":
            continue
        linea = resultados.get(item.custom_id)
        if batch.tipo == "diario":
            _aplicar_item_diario(db, item, linea, estado.status, deps, new_sancionados, stats, resolver)
            if fecha_ref is None and item.boe_document_id:
                document = db.get(BoeDocumento, item.boe_document_id)
                fecha_ref = document.fecha_publicacion if document else None
        else:
            _aplicar_item_historico(db, item, linea, estado.status, stats)
        db.flush()

    if batch.tipo == "diario" and new_sancionados:
        try:
            asignar_sanciones_a_clientes(db, new_sancionados, stats)
        except Exception:
            logger.exception("No se pudieron asignar a clientes las sanciones del batch %s", batch.id)

    batch.completados = sum(1 for item in batch.items if item.status == "completado")
    batch.errores = sum(1 for item in batch.items if item.status == "error")
    batch.sancionados_creados += stats["extracted"] if batch.tipo == "diario" else 0
    batch.status = estado.status
    if estado.detalle_error:
        batch.error_log = (batch.error_log + "\n" if batch.error_log else "") + estado.detalle_error[:2_000]
    batch.finalizado_at = datetime.now(timezone.utc)
    db.commit()

    if batch.tipo == "diario" and new_sancionados:
        try:
            deps.send_digest(new_sancionados, str(fecha_ref) if fecha_ref else "batch")
        except Exception:
            logger.exception("No se pudo enviar el digest del batch %s", batch.id)
    return stats


def procesar_batches_pendientes(dependencies: BatchDependencies | None = None) -> dict[str, Any]:
    """One polling pass over every open batch."""
    deps = dependencies or BatchDependencies()
    db = SyncSessionLocal()
    resumen: dict[str, Any] = {"revisados": 0, "finalizados": 0, "sancionados": 0, "errores": 0}
    try:
        abiertos = db.execute(
            select(ExtraccionBatch).where(ExtraccionBatch.status.in_(ESTADOS_ABIERTOS)).order_by(ExtraccionBatch.id)
        ).scalars().all()
        if not abiertos:
            return resumen
        transport = deps.transport()
        for batch in abiertos:
            resumen["revisados"] += 1
            if not batch.openai_batch_id:
                batch.status = "fallido"
                batch.error_log = "Batch sin identificador de OpenAI"
                batch.finalizado_at = datetime.now(timezone.utc)
                db.commit()
                continue
            try:
                estado = transport.consultar(batch.openai_batch_id)
            except Exception as exc:
                logger.warning("No se pudo consultar el batch %s: %s", batch.openai_batch_id, exc)
                batch.ultimo_check_at = datetime.now(timezone.utc)
                db.commit()
                continue
            batch.ultimo_check_at = datetime.now(timezone.utc)
            if estado.status not in ESTADOS_TERMINALES:
                batch.status = estado.status
                batch.completados = estado.completados
                batch.errores = estado.fallidos
                db.commit()
                continue
            stats = aplicar_batch(db, batch, estado, transport, deps)
            resumen["finalizados"] += 1
            resumen["sancionados"] += stats["extracted"]
            resumen["errores"] += stats["errors"]
        return resumen
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery.task(name="app.tasks.extraccion_batch.procesar_batches_pendientes_task")
def procesar_batches_pendientes_task() -> dict:
    return procesar_batches_pendientes()
