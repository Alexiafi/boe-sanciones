"""On-demand structured extraction (OpenAI) over selected historical
documents, for an already-converted client.

Reuses the exact same cost gates as the daily pipeline
(``app/tasks/scraping.py``): ``PaidExtractionNotAllowed``,
``openai_extraction_enabled`` + API key + an explicit
``permitir_extraccion_pago``on every call. This task does NOT create
``Sancionado``/oportunidad rows — historical documents are reference material
for an existing client, not new opportunities, and must not pollute the
30-day panel or the ``OP-`` code sequence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from app.celery_app import celery
from app.config import settings
from app.database import SyncSessionLocal
from app.models.cliente import ActividadCliente
from app.models.historico import HistoricoDoc, HistoricoResultado
from app.models.scraping_run import ScrapingRun
from app.services.boe_client import fetch_document_content, fetch_document_pdf
from app.services.configuracion import ConfiguracionRuntime, extraccion_disponible, leer_configuracion
from app.services.extractor import ResultadoExtraccion, extract_sanctions
from app.services.openai_batch import BatchTransport, PeticionBatch, enviar_batch, get_transport
from app.services.parser import RawDocument, extract_text_from_document
from app.services.archivo import guardar_archivo
from app.tasks.scraping import PaidExtractionNotAllowed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtraccionHistoricaDependencies:
    extractor: Callable[[str, str], ResultadoExtraccion] = extract_sanctions
    fetch_text: Callable[[HistoricoDoc], tuple[str, str, RawDocument | None]] | None = None
    batch_transport: Callable[[], BatchTransport] = get_transport
    leer_configuracion: Callable[[Any], ConfiguracionRuntime] = leer_configuracion


def _fetch_text_default(doc: HistoricoDoc) -> tuple[str, str, RawDocument | None]:
    return extract_text_from_document(
        doc.url_xml, doc.url_html, doc.url_pdf,
        fetch_fn=fetch_document_content, fetch_pdf_fn=fetch_document_pdf,
    )


def extraer_historico(
    resultado_ids: list[int],
    *,
    permitir_extraccion_pago: bool = False,
    force: bool = False,
    dependencies: ExtraccionHistoricaDependencies | None = None,
    modo: str | None = None,
) -> dict[str, Any]:
    """``modo`` is ``tiempo_real`` or ``batch``; ``None`` follows the runtime
    configuration (``historico_extraccion_modo``). In batch mode the selected
    documents are submitted as one Batch API job and the results land later
    via ``tasks/extraccion_batch.py`` — the returned dict then carries
    ``batch_id`` and ``en_batch`` instead of ``extraidos``."""
    if permitir_extraccion_pago and not extraccion_disponible()[0]:
        raise PaidExtractionNotAllowed("La extracción OpenAI requiere configuración habilitada y una API key.")
    allow = permitir_extraccion_pago and extraccion_disponible()[0]
    deps = dependencies or ExtraccionHistoricaDependencies()
    limite = (
        min(len(resultado_ids), settings.historico_extraccion_max_docs_por_peticion) if allow else 0
    )

    db = SyncSessionLocal()
    if modo is None:
        modo = deps.leer_configuracion(db).historico_extraccion_modo
    if modo not in ("tiempo_real", "batch"):
        modo = "tiempo_real"
    run = ScrapingRun(
        tipo="historico_cliente", fecha_boe=date.today(), status="running",
        started_at=datetime.now(timezone.utc), extraction_requested=allow,
        extraction_provider=("openai_batch" if modo == "batch" else "openai") if allow else "disabled",
        extraction_limit=limite, extraction_attempts=0,
    )
    db.add(run)
    db.commit()

    extraidos = 0
    errores = 0
    procesados: list[int] = []
    peticiones: list[PeticionBatch] = []
    try:
        for resultado_id in resultado_ids:
            if not allow or run.extraction_attempts >= limite:
                break
            resultado = db.execute(
                select(HistoricoResultado).where(HistoricoResultado.id == resultado_id)
            ).scalar_one_or_none()
            if resultado is None or (resultado.extraido and not force):
                continue

            run.extraction_attempts += 1
            doc = resultado.documento
            texto = doc.texto_plano
            if not texto:
                texto, _fuente, raw = (deps.fetch_text or _fetch_text_default)(doc)
                if raw:
                    # Re-fetching means the doc had no stored text: archive the
                    # bytes now so the next time never depends on the source.
                    guardar_archivo(
                        db, boe_id=doc.boe_id, content_type=raw[0],
                        contenido=raw[1], url_origen=raw[2],
                    )
            if modo == "batch":
                resultado.extraccion_error = None
                peticiones.append(PeticionBatch(
                    custom_id=f"hist-{resultado.id}", texto=texto or "", titulo=doc.titulo,
                    historico_resultado_id=resultado.id,
                ))
                procesados.append(resultado_id)
                db.commit()
                continue
            try:
                extraido: ResultadoExtraccion = deps.extractor(texto or "", doc.titulo)
                resultado.datos_extraidos = extraido.model_dump(mode="json")
                resultado.extraido = True
                resultado.extraido_at = datetime.now(timezone.utc)
                resultado.extractor_version = f"openai:{settings.openai_model}"
                resultado.extraccion_error = None
                db.add(ActividadCliente(
                    cliente_id=resultado.cliente_id, tipo="sistema",
                    titulo=f"Extracción histórica: {doc.titulo[:200]}",
                    datos={"historico_resultado_id": resultado.id, "historico_doc_id": doc.id},
                ))
                extraidos += 1
                procesados.append(resultado_id)
            except Exception as exc:
                resultado.extraccion_error = str(exc)[:2_000]
                errores += 1
                logger.exception("Extracción histórica fallida para resultado %s", resultado_id)
            db.commit()

        batch_id: int | None = None
        if peticiones:
            try:
                batch = enviar_batch(
                    db, tipo="historico_cliente", peticiones=peticiones, transport=deps.batch_transport(),
                    scraping_run_id=run.id,
                )
                batch_id = batch.id
                db.commit()
            except Exception as exc:
                logger.exception("No se pudo enviar el batch histórico del run %s", run.id)
                try:
                    db.commit()  # keep the ``fallido`` batch row for diagnosis
                except Exception:
                    db.rollback()
                for peticion in peticiones:
                    resultado = db.get(HistoricoResultado, peticion.historico_resultado_id)
                    if resultado is not None:
                        resultado.extraccion_error = f"Envío a OpenAI Batch fallido: {exc}"[:2_000]
                errores += len(peticiones)
                procesados = []
                db.commit()

        run.status = "completed"
        run.extracted = extraidos
        run.errors = errores
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        # Read everything needed for the return value BEFORE closing the
        # session in `finally` — after close(), these ORM attributes are
        # expired and accessing them raises DetachedInstanceError.
        resumen = {
            "run_id": run.id, "extraidos": extraidos, "errores": errores,
            "procesados": procesados, "openai_calls": run.extraction_attempts,
            "modo": modo if allow else "sin_extraccion",
            "batch_id": batch_id, "en_batch": len(peticiones) if batch_id else 0,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return resumen


@celery.task(name="app.tasks.historico_extraccion.extraer_historico_task")
def extraer_historico_task(
    resultado_ids: list[int], permitir_extraccion_pago: bool = False, force: bool = False, modo: str | None = None,
) -> dict:
    return extraer_historico(resultado_ids, permitir_extraccion_pago=permitir_extraccion_pago, force=force, modo=modo)
