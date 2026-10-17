"""Cost-controlled BOE ingestion pipeline.

The Celery task is deliberately thin. ``run_scraping`` accepts a dependency
bundle so tests can exercise the complete flow with fixtures and zero network.

A run has three separate stages, so that a slow stage never blocks the others:

1. **Ingestion** — download and persist the day's BOE documents and TEU
   notices. Downloads (network + PDF→text) run in a thread pool; every
   database write stays on the run's own thread. Free: no OpenAI.
2. **Selection** — every document of the date whose extraction is still due
   (never tried, or failed and eligible for another attempt), traffic first.
3. **Extraction** — real-time mode calls OpenAI for several documents at once
   (``OPENAI_CONCURRENCY``); batch mode queues them into one Batch API job.

The same function is *incremental*: a second run for the same date only
downloads what is still missing (late-published TEU notices, items that
failed) and only extracts what is still due, so running it every half hour
costs a couple of requests when nothing changed.

Paid extraction has two layers of control:

- the permanent ``.env`` gate (``OPENAI_EXTRACTION_ENABLED`` + API key), and
- the runtime configuration Judit edits from the UI
  (``services/configuracion.py``): whether the *scheduled* runs extract on
  their own (``extraccion_automatica``) and whether they call OpenAI in real
  time or through the Batch API (``extraccion_modo``).

A manual trigger from the "Operación" screen still carries its own explicit
``permitir_extraccion_pago`` flag, exactly as before.
"""

from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Iterator

from celery.signals import worker_ready
from sqlalchemy import func, select, text
from sqlalchemy.orm import defer

from app.celery_app import celery
from app.config import settings
from app.database import SyncSessionLocal, sync_engine
from app.models.documento import BoeDocumento
from app.models.scraping_run import ScrapingRun
from app.services.boe_client import (
    BoeSumarioNoDisponible,
    fetch_document_content,
    fetch_document_pdf,
    fetch_sumario,
    flatten_sumario,
    hash_text,
)
from app.services.classifier import classify_document, should_skip_section, verify_with_body
from app.services.configuracion import ConfiguracionRuntime, extraccion_disponible, leer_configuracion
from app.services.extractor import ResultadoExtraccion, extract_sanctions
from app.services.alertas import ejecutar_radar_clientes
from app.services.historico.indexado import upsert_from_doc_data
from app.services.historico.patterns import normalizar_identificador
from app.services.identidad import ResolverIdentidad
from app.services.notifier import create_inapp_notification, send_email_digest
from app.services.openai_batch import BatchTransport, PeticionBatch, enviar_batch, get_transport
from app.services.oportunidades import upsert_afectado
from app.services.parser import RawDocument, extract_text_from_document, pdf_to_text
from app.services.archivo import guardar_archivo
from app.services.teu_client import (
    _normalize as _normalizar_titulo,
    fetch_teu_index,
    fetch_teu_pdf,
    filter_relevant_teu_entries,
    parse_teu_index,
)
from app.services.vinculos import asignar_sancion_a_cliente, indice_identificadores

logger = logging.getLogger(__name__)

# Days back the catch-up task looks for dates without a completed run. Long
# enough to cover a laptop that was off over a long weekend (or a week with a
# broken day), short enough that it never turns into an accidental historical
# backfill.
CATCH_UP_DIAS = 10

# A run is "hung" only when its heartbeat has been silent this long. The run
# stamps a heartbeat on every document and at least every ``LATIDO_CADA_S``
# seconds, so a run that is merely slow is never touched.
RUN_COLGADO_TRAS = timedelta(minutes=20)
LATIDO_CADA_S = 20

# An errored document is retried automatically this many times in total; after
# that only a forced manual run retries it — except that a later attempt is
# allowed once ``ESPERA_REINTENTO`` has passed (an OpenAI outage must not leave
# a whole day broken until somebody notices), up to ``MAX_INTENTOS_CON_ESPERA``.
MAX_INTENTOS_AUTOMATICOS = 2
MAX_INTENTOS_CON_ESPERA = 4
ESPERA_REINTENTO = timedelta(hours=4)

# A summary item / TEU notice that fails to download this many times is given up
# on for the day (a forced run still retries it): otherwise one permanently
# broken document would make every half-hourly pass download it again and
# record a new run.
MAX_FALLOS_DESCARGA = 3

SIN_TEXTO = "No se pudo obtener texto del documento"

# Stop calling OpenAI after this many consecutive failures: a revoked key, an
# exhausted quota or an outage would otherwise fail (and bill retries for)
# hundreds of documents one after another.
MAX_FALLOS_SEGUIDOS = 5

# Title/department vocabulary that puts a notice at the front of the
# extraction queue: the morning call list is built from traffic fines first.
_PALABRAS_PRIORITARIAS = (
    "trafico", "circulacion", "denuncia", "transit", "velocidad", "estacionamiento",
    "movilidad", "vehiculo", "conducir", "conduccion",
)


class PaidExtractionNotAllowed(ValueError):
    """Raised when a manual request has not passed both cost-control gates."""


@dataclass(frozen=True)
class PipelineDependencies:
    fetch_sumario: Callable[[date], dict] = fetch_sumario
    flatten_sumario: Callable[[dict, date], list[dict[str, Any]]] = flatten_sumario
    fetch_text: Callable[[dict[str, Any]], tuple[str, str, RawDocument | None]] | None = None
    extractor: Callable[[str, str], ResultadoExtraccion] = extract_sanctions
    send_digest: Callable[[list, str], None] = send_email_digest
    notify: Callable[[Any, Any], None] = create_inapp_notification
    fetch_teu_index: Callable[[date], str] = fetch_teu_index
    parse_teu_index: Callable[[str, date], list[dict[str, Any]]] = parse_teu_index
    filter_teu_entries: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = filter_relevant_teu_entries
    fetch_teu_pdf: Callable[[str], bytes] = fetch_teu_pdf
    # Batch API transport factory; only invoked when a run actually has
    # documents to submit in batch mode (never at import or construction).
    batch_transport: Callable[[], BatchTransport] = get_transport
    # Runtime configuration loader; tests override to pin a mode.
    leer_configuracion: Callable[[Any], ConfiguracionRuntime] = leer_configuracion


def _fetch_text(doc_data: dict[str, Any]) -> tuple[str, str, RawDocument | None]:
    return extract_text_from_document(
        doc_data.get("url_xml"), doc_data.get("url_html"), doc_data.get("url_pdf"),
        fetch_fn=fetch_document_content, fetch_pdf_fn=fetch_document_pdf,
    )


def _get_text(deps: PipelineDependencies, doc_data: dict[str, Any]) -> tuple[str, str, RawDocument | None]:
    return (deps.fetch_text or _fetch_text)(doc_data)


def _guess_familia_from_section(doc_data: dict[str, Any]) -> str:
    sec = (doc_data.get("seccion_codigo") or "")
    if sec.startswith("5"):
        return "anuncio_expediente"
    if sec == "3":
        return "sancion_firme"
    if sec == "4":
        return "administracion_justicia"
    return "otro"


def _try_acquire_lock(db, target_date: date) -> bool:
    """Use a session-level PostgreSQL advisory lock for one BOE date."""
    value = db.execute(
        text("SELECT pg_try_advisory_lock(hashtext(:key))"),
        {"key": f"boe-scraping:{target_date.isoformat()}"},
    ).scalar()
    return bool(value)


def _release_lock(db, target_date: date) -> None:
    db.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": f"boe-scraping:{target_date.isoformat()}"})


# --------------------------------------------------------------------------
# Progress / liveness
# --------------------------------------------------------------------------

def _latido(db, run: ScrapingRun | None, *, fase: str | None = None, actual: int | None = None, total: int | None = None) -> None:
    """Stamp the run's heartbeat (and, optionally, where it is). Commits, which
    also flushes any document status changes made since the last commit."""
    if run is None or run.id is None:
        return
    run.heartbeat_at = datetime.now(timezone.utc)
    if fase is not None:
        run.fase = fase
    if actual is not None:
        run.progreso_actual = actual
    if total is not None:
        run.progreso_total = total
    db.commit()


def _iterar_paralelo(
    items: Iterable[Any], funcion: Callable[[Any], Any], trabajadores: int, *,
    latido: Callable[[], None] | None = None,
) -> Iterator[tuple[Any, Any, Exception | None]]:
    """Run ``funcion`` over ``items`` in a thread pool and yield
    ``(item, resultado, error)`` as each finishes. At most ``2 × trabajadores``
    items are in flight, so memory stays bounded however long the list is, and
    ``latido`` is called at least every ``LATIDO_CADA_S`` seconds."""
    # ``items`` may be a lazy generator whose side effects must happen only as
    # each item enters the window (see ``_extraer_tiempo_real``), so it is
    # never materialised.
    trabajadores = max(1, trabajadores)
    with ThreadPoolExecutor(max_workers=trabajadores, thread_name_prefix="pipeline") as pool:
        en_vuelo: dict[Future, Any] = {}
        cola = iter(items)
        agotada = False
        while True:
            while not agotada and len(en_vuelo) < trabajadores * 2:
                try:
                    item = next(cola)
                except StopIteration:
                    agotada = True
                    break
                en_vuelo[pool.submit(funcion, item)] = item
            if not en_vuelo:
                return
            hechos, _ = wait(en_vuelo, timeout=LATIDO_CADA_S, return_when=FIRST_COMPLETED)
            if latido is not None:
                latido()
            for futuro in hechos:
                item = en_vuelo.pop(futuro)
                try:
                    yield item, futuro.result(), None
                except Exception as exc:  # noqa: BLE001 - reported to the caller per item
                    yield item, None, exc


# --------------------------------------------------------------------------
# Ingestion (free)
# --------------------------------------------------------------------------

def _document_from_data(db, doc_data: dict[str, Any], text_value: str | None, source: str, confidence: float, rules: list[str], familia: str) -> BoeDocumento:
    document = BoeDocumento(
        boe_id=doc_data["identificador"],
        fecha_publicacion=doc_data["fecha_publicacion"],
        diario_numero=doc_data.get("diario_numero"),
        seccion_codigo=doc_data.get("seccion_codigo"),
        seccion_nombre=doc_data.get("seccion_nombre"),
        departamento_codigo=doc_data.get("departamento_codigo"),
        departamento_nombre=doc_data.get("departamento_nombre"),
        epigrafe_nombre=doc_data.get("epigrafe_nombre"),
        titulo=doc_data["titulo"],
        texto_plano=text_value[:50_000] if text_value else None,
        hash_texto=hash_text(text_value) if text_value else None,
        familia_sancionadora=familia,
        confidence=confidence,
        match_rules=rules,
        url_html=doc_data.get("url_html"),
        url_xml=doc_data.get("url_xml"),
        url_pdf=doc_data.get("url_pdf"),
        raw_sumario_item=doc_data.get("raw_item"),
        source=f"boe_api_{source}",
        extraction_status="pending",
    )
    db.add(document)
    db.flush()
    return document


def _ingestar_candidato(
    db, doc_data: dict[str, Any], text_value: str, source: str, rules: list[str], confidence: float,
    familia: str, stats: dict[str, int],
) -> BoeDocumento:
    """Persist one candidate document and index it for free. Extraction is not
    decided here (see ``_seleccionar_trabajos``)."""
    stats["candidates"] += 1
    existing = db.execute(select(BoeDocumento).where(BoeDocumento.boe_id == doc_data["identificador"])).scalar_one_or_none()
    document = existing or _document_from_data(db, doc_data, text_value, source, confidence, rules, familia)

    if existing and not document.texto_plano and text_value:
        document.texto_plano = text_value[:50_000]
        document.hash_texto = hash_text(text_value)
        if document.extraction_status == "error" and document.extraction_error == SIN_TEXTO:
            # The text arrived on a later pass: the document is extractable now.
            document.extraction_status, document.extraction_error, document.extraction_intentos = "pending", None, 0
    if not document.texto_plano and not text_value and document.extraction_status == "pending":
        # Nothing to send to OpenAI. Marked as exhausted so selection (and the
        # catch-up) do not come back for it every pass; a later successful
        # download resets it (above).
        document.extraction_status, document.extraction_error = "error", SIN_TEXTO
        document.extraction_intentos = MAX_INTENTOS_CON_ESPERA
        stats["errors"] += 1

    # Free daily accumulation into the historical index: this candidate's
    # text is already in memory, so indexing it costs one extra INSERT/UPDATE
    # and zero network/LLM calls. This is the only way TEU history older than
    # its public 90-day window will ever exist (see historico/teu_publico.py).
    if settings.historico_indexado_diario_enabled:
        try:
            fuente_historico = "teu" if familia == "notificacion_teu" else "boe"
            upsert_from_doc_data(
                db, doc_data, text_value or document.texto_plano, fuente=fuente_historico,
                origen_indexado="diario", familia_sancionadora=familia, confidence=confidence,
                guardar_texto=True,
            )
        except Exception:
            logger.exception("No se pudo indexar %s en el histórico diario", doc_data.get("identificador"))
    return document


def _juzgar_y_guardar_boe(
    db, doc_data: dict[str, Any], text_value: str, source: str, raw: RawDocument | None, stats: dict[str, int],
) -> None:
    title_candidate, title_rules, title_confidence, familia = classify_document(doc_data)
    body_ok, body_rules = verify_with_body(text_value) if text_value else (False, [])
    if not title_candidate and not body_ok:
        return
    if raw:
        # Archive the original bytes the moment we decide to persist the
        # document: BOE notification supplements and the TEU remove documents
        # after a period, and this copy is what keeps the original viewable
        # afterwards.
        guardar_archivo(
            db, boe_id=doc_data["identificador"], content_type=raw[0],
            contenido=raw[1], url_origen=raw[2],
        )
    rules = title_rules + body_rules if title_candidate else body_rules
    confidence = max(title_confidence, 0.85 if len(body_rules) >= 3 else 0.65) if title_candidate else (0.85 if len(body_rules) >= 3 else 0.65)
    _ingestar_candidato(
        db, doc_data, text_value, source, rules, confidence, familia or _guess_familia_from_section(doc_data), stats,
    )


def _boe_por_descargar(
    db, docs: list[dict[str, Any]], ya_revisados: set[str], force: bool, ya_fallidos: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """The summary items that still need downloading, and the set of items
    that need no download because they are already persisted with their text.

    Persisted documents already have their text; documents judged in an
    earlier run of this date are not downloaded again (``force`` re-judges)."""
    candidatos = [d for d in docs if d.get("identificador") and not should_skip_section(d)]
    ids = [d["identificador"] for d in candidatos]
    con_texto = set(db.execute(
        select(BoeDocumento.boe_id).where(BoeDocumento.boe_id.in_(ids), BoeDocumento.texto_plano.is_not(None))
    ).scalars().all()) if ids else set()
    ya_fallidos = ya_fallidos or {}
    a_descargar = [
        d for d in candidatos
        if d["identificador"] not in con_texto
        and (force or (d["identificador"] not in ya_revisados and ya_fallidos.get(d["identificador"], 0) < MAX_FALLOS_DESCARGA))
    ]
    return a_descargar, con_texto


def _fase_boe(
    db, run: ScrapingRun, docs: list[dict[str, Any]], ya_revisados: set[str], deps: PipelineDependencies,
    stats: dict[str, int], force: bool, revisados: set[str], fallos: dict[str, int],
) -> None:
    stats["total_docs"] = len(docs)
    a_descargar, con_texto = _boe_por_descargar(db, docs, ya_revisados, force, fallos)
    revisados.update(con_texto)
    revisados.update(ya_revisados if not force else set())
    _latido(db, run, fase="descargando_boe", actual=0, total=len(a_descargar))

    hecho = 0
    for doc_data, resultado, error in _iterar_paralelo(
        a_descargar, lambda d: _get_text(deps, d), settings.descarga_workers, latido=lambda: _latido(db, run),
    ):
        hecho += 1
        identificador = doc_data.get("identificador")
        if error is not None:
            stats["errors"] += 1
            fallos[identificador] = fallos.get(identificador, 0) + 1
            logger.warning("No se pudo descargar el documento BOE %s: %s", identificador, error)
            continue
        text_value, source, raw = resultado
        stats["scanned"] += 1
        try:
            _juzgar_y_guardar_boe(db, doc_data, text_value, source, raw, stats)
            _latido(db, run, actual=hecho)
            if text_value:
                revisados.add(identificador)
            else:
                # Every URL failed (the fetcher swallows the errors): count it,
                # so a document that never answers is given up on.
                fallos[identificador] = fallos.get(identificador, 0) + 1
        except Exception:
            db.rollback()
            stats["errors"] += 1
            fallos[identificador] = fallos.get(identificador, 0) + 1
            logger.exception("No se pudo procesar el documento BOE %s", identificador)


def _fase_teu(
    db, run: ScrapingRun, entries: list[dict[str, Any]], deps: PipelineDependencies, stats: dict[str, int],
    max_entries: int, ya_revisados: set[str], revisados: set[str], fallos: dict[str, int], force: bool,
) -> None:
    """TEU intake. One notice at a time, each in its own transaction: a 502
    from the BOE on a single PDF (seen in production) must cost that notice,
    not the other thousand of the day."""
    seleccion = entries[:max_entries]
    nuevas = _entradas_teu_nuevas(db, seleccion, ya_revisados, fallos, force)
    _latido(db, run, fase="descargando_teu", actual=0, total=len(nuevas))

    def descargar(entry: dict[str, Any]) -> tuple[bytes, str]:
        pdf = deps.fetch_teu_pdf(entry["url_pdf"])
        return pdf, pdf_to_text(pdf)

    hecho = 0
    for entry, resultado, error in _iterar_paralelo(
        nuevas, descargar, settings.descarga_workers, latido=lambda: _latido(db, run),
    ):
        hecho += 1
        identificador = entry.get("identificador")
        if error is not None:
            stats["errors"] += 1
            fallos[identificador] = fallos.get(identificador, 0) + 1
            logger.warning("No se pudo descargar el aviso TEU %s: %s", identificador, error)
            continue
        pdf, content = resultado
        if not content:
            # A PDF with no extractable text (a scan) will not have any next
            # time either: remember it instead of downloading it every pass.
            revisados.add(identificador)
            continue
        try:
            # The TEU removes notifications from its public site after ~90 days;
            # archive the PDF bytes so the original stays viewable afterwards.
            guardar_archivo(
                db, boe_id=entry["identificador"], content_type="application/pdf",
                contenido=pdf, url_origen=entry["url_pdf"],
            )
            document = BoeDocumento(
                boe_id=entry["identificador"], fecha_publicacion=entry["fecha_publicacion"],
                seccion_codigo="TEU", seccion_nombre="Tablón Edictal Único",
                departamento_nombre=entry.get("departamento_nombre"), titulo=entry["titulo"],
                texto_plano=content[:50_000], hash_texto=hash_text(content),
                familia_sancionadora="notificacion_teu", confidence=0.80,
                match_rules=["teu_title_match"], url_pdf=entry["url_pdf"], source="teu_pdf",
                extraction_status="pending",
            )
            db.add(document)
            db.flush()
            _ingestar_candidato(db, entry, content, "pdf", ["teu_title_match"], 0.80, "notificacion_teu", stats)
            _latido(db, run, actual=hecho)
        except Exception:
            db.rollback()
            stats["errors"] += 1
            fallos[identificador] = fallos.get(identificador, 0) + 1
            logger.exception("No se pudo procesar el aviso TEU %s", identificador)


def _entradas_teu_nuevas(
    db, entries: list[dict[str, Any]], ya_revisados: set[str] | None = None,
    ya_fallidos: dict[str, int] | None = None, force: bool = False,
) -> list[dict[str, Any]]:
    """TEU notices still to download: not stored yet, not known to be empty and
    not given up on after repeated failures (``force`` retries everything)."""
    ids = [e["identificador"] for e in entries]
    if not ids:
        return []
    existentes = set(db.execute(select(BoeDocumento.boe_id).where(BoeDocumento.boe_id.in_(ids))).scalars().all())
    ya_revisados, ya_fallidos = ya_revisados or set(), ya_fallidos or {}
    return [
        e for e in entries
        if e["identificador"] not in existentes
        and (force or (e["identificador"] not in ya_revisados and ya_fallidos.get(e["identificador"], 0) < MAX_FALLOS_DESCARGA))
    ]


# --------------------------------------------------------------------------
# Selection + extraction (paid)
# --------------------------------------------------------------------------

@dataclass
class _Trabajo:
    document_id: int
    titulo: str
    prioridad: int = 1


@dataclass
class _ContextoExtraccion:
    """Per-run extraction decisions, resolved once in ``run_scraping``."""

    allow: bool
    limit: int
    modo: str  # "tiempo_real" | "batch"
    resolver: ResolverIdentidad | None = None
    pendientes_batch: list[PeticionBatch] = field(default_factory=list)


def _en_batch_abierto(db, document_id: int) -> bool:
    """True while the document sits in a batch OpenAI has not finished:
    even ``force`` must not re-queue it (that would pay for it twice). Once
    the batch is terminal the item is no longer ``pendiente`` and a forced
    run may retry the document."""
    from app.models.extraccion_batch import ExtraccionBatch, ExtraccionBatchItem

    return bool(
        db.execute(
            select(ExtraccionBatchItem.id)
            .join(ExtraccionBatch, ExtraccionBatch.id == ExtraccionBatchItem.batch_id)
            .where(
                ExtraccionBatchItem.boe_document_id == document_id,
                ExtraccionBatchItem.status == "pendiente",
                ExtraccionBatch.status.in_(("preparando", "enviado", "en_progreso")),
            )
            .limit(1)
        ).scalar_one_or_none()
    )


def _prioridad(titulo: str, departamento: str | None) -> int:
    texto = _normalizar_titulo(f"{titulo} {departamento or ''}")
    return 0 if any(palabra in texto for palabra in _PALABRAS_PRIORITARIAS) else 1


def _intento_automatico_permitido(documento: BoeDocumento, ahora: datetime) -> bool:
    intentos = documento.extraction_intentos or 0
    if intentos < MAX_INTENTOS_AUTOMATICOS:
        return True
    ultimo = documento.extraction_attempted_at
    if ultimo is not None and ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=timezone.utc)
    return intentos < MAX_INTENTOS_CON_ESPERA and ultimo is not None and ahora - ultimo >= ESPERA_REINTENTO


def _seleccionar_trabajos(db, target_date: date, force: bool, limite: int | None = None) -> list[_Trabajo]:
    """Documents of ``target_date`` whose extraction is due, traffic first.

    "completed" is done for good — re-extracting an already extracted document
    is pure cost (``upsert_afectado`` is idempotent), so not even ``force``
    does it; ``force`` retries errored documents past the automatic limit and
    queued-but-unfinished ones. "batch_pending" is already in a batch that has
    not come back yet — re-queueing it would pay twice."""
    ahora = datetime.now(timezone.utc)
    documentos = db.execute(
        select(BoeDocumento)
        .options(defer(BoeDocumento.texto_plano))
        .where(BoeDocumento.fecha_publicacion == target_date, (BoeDocumento.source.is_(None)) | (BoeDocumento.source != "manual"))
        .order_by(BoeDocumento.id)
    ).scalars().all()
    elegidos: list[_Trabajo] = []
    for documento in documentos:
        estado = documento.extraction_status
        if estado == "completed":
            continue
        if estado == "batch_pending" and (not force or _en_batch_abierto(db, documento.id)):
            continue
        if estado == "error" and not force and not _intento_automatico_permitido(documento, ahora):
            continue
        elegidos.append(_Trabajo(documento.id, documento.titulo, _prioridad(documento.titulo, documento.departamento_nombre)))
    elegidos.sort(key=lambda trabajo: trabajo.prioridad)  # stable: id order inside each priority
    return elegidos[:limite] if limite is not None else elegidos


def _aplicar_extraccion(
    db, document: BoeDocumento, result: ResultadoExtraccion, deps: PipelineDependencies,
    ctx: _ContextoExtraccion, new_sancionados: list, stats: dict[str, int],
) -> None:
    try:
        aplicar_resultado_documento(db, document, result, deps.notify, new_sancionados, stats, resolver=ctx.resolver)
    except Exception as exc:
        if not db.is_active:
            # A failed flush leaves the session in "needs rollback"; clear it
            # so the document's error state (and the rest of the run) can
            # still be written.
            db.rollback()
        document = db.get(BoeDocumento, document.id)
        document.extraction_status = "error"
        document.extraction_error = str(exc)[:2_000]
        stats["errors"] += 1
        logger.exception("Structured extraction failed for %s", document.boe_id)


def _extraer_tiempo_real(
    db, run: ScrapingRun, trabajos: list[_Trabajo], deps: PipelineDependencies, ctx: _ContextoExtraccion,
    new_sancionados: list, stats: dict[str, int],
) -> None:
    """Call OpenAI for several documents at once. Each worker only sees plain
    strings; documents, notifications and commits stay on this thread."""
    hecho = 0
    seguidos_fallidos = 0
    detenida = False
    _latido(db, run, fase="extrayendo", actual=0, total=len(trabajos))

    def preparar(trabajo: _Trabajo) -> tuple[_Trabajo, str] | None:
        documento = db.get(BoeDocumento, trabajo.document_id)
        texto = documento.texto_plano
        if not texto:
            if documento.extraction_status != "error" or documento.extraction_error != SIN_TEXTO:
                documento.extraction_status, documento.extraction_error = "error", SIN_TEXTO
                documento.extraction_intentos = MAX_INTENTOS_CON_ESPERA
                stats["errors"] += 1
            return None
        run.extraction_attempts += 1
        documento.extraction_attempted_at = datetime.now(timezone.utc)
        documento.extraction_intentos = (documento.extraction_intentos or 0) + 1
        documento.extractor_version = f"openai:{settings.openai_model}"
        return trabajo, texto

    def candidatos() -> Iterator[tuple[_Trabajo, str]]:
        for trabajo in trabajos:
            if detenida:
                return
            preparado = preparar(trabajo)
            if preparado is not None:
                yield preparado

    for (trabajo, texto), resultado, error in _iterar_paralelo(
        candidatos(), lambda par: deps.extractor(par[1], par[0].titulo), settings.openai_concurrency,
        latido=lambda: _latido(db, run),
    ):
        hecho += 1
        documento = db.get(BoeDocumento, trabajo.document_id)
        if error is not None:
            seguidos_fallidos += 1
            documento.extraction_status = "error"
            documento.extraction_error = str(error)[:2_000]
            stats["errors"] += 1
            logger.warning("Extracción fallida para %s: %s", documento.boe_id, error)
            if seguidos_fallidos >= MAX_FALLOS_SEGUIDOS and not detenida:
                detenida = True
                stats["extraccion_detenida"] = True
                run.error_log = (
                    f"Extracción OpenAI detenida tras {seguidos_fallidos} errores seguidos "
                    f"(último: {str(error)[:300]}). Los documentos restantes quedan pendientes."
                )
                logger.error(run.error_log)
        else:
            seguidos_fallidos = 0
            _aplicar_extraccion(db, documento, resultado, deps, ctx, new_sancionados, stats)
        _latido(db, run, actual=hecho)


def _encolar_batch(db, run: ScrapingRun, trabajos: list[_Trabajo], ctx: _ContextoExtraccion, stats: dict[str, int]) -> None:
    for trabajo in trabajos:
        documento = db.get(BoeDocumento, trabajo.document_id)
        if not documento.texto_plano:
            if documento.extraction_error != SIN_TEXTO:
                documento.extraction_status, documento.extraction_error = "error", SIN_TEXTO
                documento.extraction_intentos = MAX_INTENTOS_CON_ESPERA
                stats["errors"] += 1
            continue
        run.extraction_attempts += 1
        documento.extraction_status = "batch_pending"
        documento.extraction_error = None
        documento.extraction_attempted_at = datetime.now(timezone.utc)
        documento.extraction_intentos = (documento.extraction_intentos or 0) + 1
        documento.extractor_version = f"openai-batch:{settings.openai_model}"
        ctx.pendientes_batch.append(PeticionBatch(
            custom_id=f"doc-{documento.id}", texto=documento.texto_plano, titulo=documento.titulo,
            boe_document_id=documento.id,
        ))
    db.commit()


def aplicar_resultado_documento(
    db, document: BoeDocumento, result: ResultadoExtraccion, notify: Callable[[Any, Any], None],
    new_sancionados: list, stats: dict[str, int], resolver: ResolverIdentidad | None = None,
) -> int:
    """Persist one document's structured extraction result — the single
    place that turns ``ResultadoExtraccion`` into opportunities, used by both
    the real-time path below and the Batch API path
    (``tasks/extraccion_batch.py``). Returns how many opportunities it created.

    A new opportunity is first resolved against what is already known about
    its party (``resolver``: attached to the client that owns that DNI/CIF,
    name and contact data inherited) and only then announced, so the alert
    already says who it is."""
    creados = 0
    fallidos = 0
    for affected in result.afectados if result.es_documento_relevante else []:
        # SAVEPOINT per affected party: a bad row (constraint violation,
        # unexpected value) must cost one opportunity, not the document and
        # certainly not the session for the rest of the run.
        try:
            with db.begin_nested():
                opportunity, created = upsert_afectado(db, document, affected)
                if opportunity is not None and created:
                    if resolver is not None:
                        try:
                            with db.begin_nested():
                                resolver(opportunity, stats)
                        except Exception:
                            logger.exception("No se pudo resolver la identidad de %s", opportunity.codigo)
                    notify(db, opportunity)
        except Exception:
            fallidos += 1
            logger.exception("No se pudo persistir un afectado de %s", document.boe_id)
            continue
        if opportunity is not None and created:
            new_sancionados.append(opportunity)
            stats["extracted"] += 1
            creados += 1
    document.extraction_status = "completed"
    document.extraction_error = f"{fallidos} afectado(s) no se pudieron guardar" if fallidos else None
    return creados


def _asignar_sanciones_a_clientes_existentes(db, new_sancionados: list, stats: dict[str, int]) -> None:
    """Safety net for opportunities created without a resolver (older callers):
    attach them to an existing client by identifier. Opportunities already
    resolved on arrival are left untouched by ``asignar_sancion_a_cliente``."""
    if not new_sancionados:
        return
    indice = indice_identificadores(db)
    for sancionado in new_sancionados:
        clave = normalizar_identificador(sancionado.identificador)
        if not clave or clave not in indice:
            continue
        cliente_id, vinculo_id = indice[clave]
        if asignar_sancion_a_cliente(db, sancionado, cliente_id, vinculo_id):
            stats["clientes_asignados"] = int(stats.get("clientes_asignados", 0)) + 1


def asignar_sanciones_a_clientes(db, new_sancionados: list, stats: dict[str, int]) -> None:
    """Public alias used by the batch result task."""
    _asignar_sanciones_a_clientes_existentes(db, new_sancionados, stats)


def _enviar_batch_diario(db, run: ScrapingRun, ctx: _ContextoExtraccion, deps: PipelineDependencies, stats: dict[str, int]) -> None:
    """Submit this run's queued documents as one Batch API job. A submission
    failure marks every queued document ``error`` (a later run with
    ``force`` retries them) and never fails the run itself — the day's
    ingestion and free indexing are already persisted."""
    if not ctx.pendientes_batch:
        return
    ids = [p.boe_document_id for p in ctx.pendientes_batch]
    try:
        batch = enviar_batch(
            db, tipo="diario", peticiones=ctx.pendientes_batch, transport=deps.batch_transport(),
            scraping_run_id=run.id,
        )
        stats["batch_id"] = batch.id
        stats["batch_enviados"] = len(ctx.pendientes_batch)
        db.commit()
    except Exception as exc:
        logger.exception("No se pudo enviar el batch OpenAI del run %s", run.id)
        # Keep the ``fallido`` batch row enviar_batch left behind (it is the
        # operator's only trace of what went wrong); only fall back to a
        # rollback if the session itself is unusable.
        try:
            db.commit()
        except Exception:
            db.rollback()
        docs = db.execute(select(BoeDocumento).where(BoeDocumento.id.in_(ids))).scalars().all()
        for document in docs:
            document.extraction_status = "error"
            document.extraction_error = f"Envío a OpenAI Batch fallido: {exc}"[:2_000]
        stats["errors"] += len(docs)
        db.commit()


def _extraccion_automatica_permitida(config: ConfiguracionRuntime) -> bool:
    """What a *scheduled* run does when nobody passed an explicit flag."""
    disponible, motivo = extraccion_disponible()
    if not config.extraccion_automatica:
        logger.info("Extracción automática desactivada en configuración; el run indexa sin OpenAI")
        return False
    if not disponible:
        logger.warning("Extracción automática configurada pero no disponible: %s", motivo)
        return False
    return True


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

def run_scraping(
    fecha_str: str | None = None, force: bool = False, permitir_extraccion_pago: bool | None = False,
    dependencies: PipelineDependencies | None = None, modo_extraccion: str | None = None,
) -> dict[str, int | bool | str]:
    """Run one date (incrementally: see the module docstring).

    ``permitir_extraccion_pago``:
    - ``True``  — explicit manual request; raises if the ``.env`` gates are closed.
    - ``False`` — never call OpenAI (indexing only).
    - ``None``  — scheduled run: follow the runtime configuration
      (``extraccion_automatica``) and the ``.env`` gates, silently indexing
      without OpenAI when either says no.
    ``modo_extraccion`` overrides the configured ``extraccion_modo`` for this run.
    """
    target_date = date.fromisoformat(fecha_str) if fecha_str else date.today()
    deps = dependencies or PipelineDependencies()
    if permitir_extraccion_pago is True and not extraccion_disponible()[0]:
        raise PaidExtractionNotAllowed("La extracción OpenAI requiere configuración habilitada y una API key.")

    db = SyncSessionLocal()
    lock_connection = sync_engine.connect()
    stats: dict[str, int | bool | str] = {
        "total_docs": 0, "candidates": 0, "extracted": 0, "errors": 0, "scanned": 0, "openai_calls": 0,
        "clientes_asignados": 0,
    }
    new_sancionados: list = []
    lock_acquired = False
    run: ScrapingRun | None = None

    try:
        config = deps.leer_configuracion(db)
        if permitir_extraccion_pago is None:
            allow_extraction = _extraccion_automatica_permitida(config)
        else:
            allow_extraction = bool(permitir_extraccion_pago) and extraccion_disponible()[0]
        modo = modo_extraccion or config.extraccion_modo
        if modo not in ("tiempo_real", "batch"):
            modo = "tiempo_real"
        limit = config.extraccion_max_docs_por_ejecucion if allow_extraction else 0
        if allow_extraction and limit <= 0:
            # A cap of 0 (set in "Configuración") is "pause the paid extraction":
            # treating it as allowed would leave every pass believing there is
            # work due (and recording a run) while never doing any.
            allow_extraction = False
        ctx = _ContextoExtraccion(allow=allow_extraction, limit=limit, modo=modo, resolver=ResolverIdentidad(db))
        stats["modo_extraccion"] = modo if allow_extraction else "sin_extraccion"

        # Keep the session-level PostgreSQL lock on a dedicated connection.
        # The work session commits after each document, so it must not own it.
        lock_acquired = _try_acquire_lock(lock_connection, target_date)
        if not lock_acquired:
            return {**stats, "skipped": True, "reason": "already_running"}

        # tipo == "diario" only: a same-day historico_cliente extraction audit
        # row (tasks/historico_extraccion.py) must never make this pipeline
        # believe the day's real BOE ingestion already ran.
        runs_previos = db.execute(
            select(ScrapingRun).where(ScrapingRun.fecha_boe == target_date, ScrapingRun.tipo == "diario")
            .order_by(ScrapingRun.id.desc())
        ).scalars().all()
        previous = next((r for r in runs_previos if r.status == "completed"), None)
        ya_revisados: set[str] = set()
        ya_fallidos: dict[str, int] = {}
        for previo in runs_previos:
            ya_revisados.update(previo.ids_revisados or [])
            for identificador, veces in (previo.ids_fallidos or {}).items():
                ya_fallidos[identificador] = max(ya_fallidos.get(identificador, 0), int(veces))
        hoy = date.today()

        # Does the BOE summary need (re)examining? Yes for a date never completed
        # and for one that completed with errors (only what failed is fetched
        # again, see ``ids_revisados``); a clean completed date is final.
        necesita_boe = force or previous is None or (previous.errors or 0) > 0
        # The TEU supplement can be published after the first run of the day (or
        # fail transiently): today and yesterday always check for new notices.
        revisa_teu = necesita_boe or target_date >= hoy - timedelta(days=1)

        # Fetch the summary BEFORE creating the run row: a not-yet-published
        # edition (404 at 07:30, Sundays, holidays) is not a failed run, it is
        # simply "nothing to do yet" — the beat schedule will try again.
        payload = None
        if necesita_boe:
            try:
                payload = deps.fetch_sumario(target_date)
            except BoeSumarioNoDisponible as exc:
                logger.info("Sin sumario del BOE para %s todavía: %s", target_date, exc)
                return {**stats, "skipped": True, "reason": "boe_no_publicado"}

        teu_entries: list[dict[str, Any]] | None = None
        teu_error: Exception | None = None
        if revisa_teu:
            try:
                teu_entries = deps.filter_teu_entries(deps.parse_teu_index(deps.fetch_teu_index(target_date), target_date))
            except Exception as exc:  # the index itself unreachable: not worth a failed run
                teu_error = exc
                logger.exception("TEU ingestion failed for %s", target_date)

        teu_nuevas = _entradas_teu_nuevas(
            db, (teu_entries or [])[:config.teu_max_por_ejecucion], ya_revisados, ya_fallidos, force,
        )
        debidos = _seleccionar_trabajos(db, target_date, force) if allow_extraction else []
        # A date that completed earlier is re-examined only if something is
        # really new: summary items never judged, TEU notices not yet stored,
        # or documents whose extraction is due.
        docs_boe: list[dict[str, Any]] | None = None
        boe_pendiente = payload is not None
        if previous is not None and not force and payload is not None:
            docs_boe = deps.flatten_sumario(payload, target_date)
            boe_pendiente = bool(_boe_por_descargar(db, docs_boe, ya_revisados, force, ya_fallidos)[0])
        if previous is not None and not boe_pendiente and not teu_nuevas and not debidos:
            return {
                **stats, "skipped": True,
                "reason": f"already_completed (run #{previous.id})" if teu_error is None else "teu_no_disponible",
            }

        ahora = datetime.now(timezone.utc)
        run = ScrapingRun(
            fecha_boe=target_date, tipo="diario", status="running", started_at=ahora, heartbeat_at=ahora,
            fase="iniciando", extraction_requested=allow_extraction,
            extraction_provider=("openai_batch" if modo == "batch" else "openai") if allow_extraction else "disabled",
            extraction_limit=limit, extraction_attempts=0,
        )
        db.add(run)
        db.commit()
        if teu_error is not None:
            stats["errors"] += 1

        revisados: set[str] = set()
        fallos: dict[str, int] = dict(ya_fallidos)
        if payload is not None:
            docs = docs_boe if docs_boe is not None else deps.flatten_sumario(payload, target_date)
            _fase_boe(db, run, docs, ya_revisados, deps, stats, force, revisados, fallos)
        if teu_entries is not None:
            stats["total_docs"] += len(teu_entries)
            _fase_teu(db, run, teu_entries, deps, stats, config.teu_max_por_ejecucion, ya_revisados, revisados, fallos, force)
        run.ids_revisados = sorted(revisados | ya_revisados) if (payload is not None or ya_revisados or revisados) else None
        # Cumulative failure counts (those that finally succeeded are dropped).
        run.ids_fallidos = {k: v for k, v in fallos.items() if k not in revisados} or None
        db.commit()

        # Extraction. Selected AFTER ingestion so the day's new documents are
        # included; the limit caps OpenAI requests per run, not ingestion.
        if allow_extraction:
            trabajos = _seleccionar_trabajos(db, target_date, force, limite=limit)
            if ctx.modo == "batch":
                _latido(db, run, fase="encolando_batch", actual=0, total=len(trabajos))
                _encolar_batch(db, run, trabajos, ctx, stats)
                _enviar_batch_diario(db, run, ctx, deps, stats)
            else:
                _extraer_tiempo_real(db, run, trabajos, deps, ctx, new_sancionados, stats)

        # Safety net + free radar over the already-indexed historical documents
        # — the only detection path that still catches a client's new sanction
        # when OpenAI extraction was disabled today. Isolated: a bug here must
        # not lose an already persisted day's ingestion.
        _latido(db, run, fase="alertas")
        try:
            _asignar_sanciones_a_clientes_existentes(db, new_sancionados, stats)
        except Exception:
            logger.exception("No se pudieron asignar sanciones a clientes existentes para %s", target_date)
        try:
            ejecutar_radar_clientes(db)
        except Exception:
            logger.exception("El radar de alertas de clientes falló para %s", target_date)

        run.status = "completed"
        run.fase = "completado"
        run.total_docs = int(stats["total_docs"])
        run.candidates = int(stats["candidates"])
        run.extracted = int(stats["extracted"])
        run.errors = int(stats["errors"])
        run.finished_at = datetime.now(timezone.utc)
        run.heartbeat_at = run.finished_at
        db.commit()
        if new_sancionados:
            deps.send_digest(new_sancionados, str(target_date))
        return {**stats, "openai_calls": run.extraction_attempts}
    except Exception as exc:
        db.rollback()
        logger.exception("Scraping pipeline failed for %s", target_date)
        # Leave a diagnosable trace instead of a row stuck in "running" forever.
        if run is not None and run.id is not None:
            try:
                run.status = "failed"
                run.fase = "fallido"
                run.error_log = str(exc)[:4_000]
                run.finished_at = datetime.now(timezone.utc)
                run.total_docs = int(stats["total_docs"])
                run.candidates = int(stats["candidates"])
                run.extracted = int(stats["extracted"])
                run.errors = int(stats["errors"])
                db.commit()
            except Exception:
                logger.exception("No se pudo marcar el run %s como fallido", run.id)
                db.rollback()
        return {**stats, "error": str(exc)}
    finally:
        if lock_acquired:
            try:
                _release_lock(lock_connection, target_date)
                lock_connection.commit()
            except Exception:
                pass
        lock_connection.close()
        db.close()


def marcar_runs_colgados(db, *, ahora: datetime | None = None) -> int:
    """Flip runs left in ``running`` by a dead worker to ``failed`` so the
    "Operación" screen never shows a phantom in-progress run and so a later
    attempt for the same date is not confused by it. "Left behind" means the
    heartbeat (or, for runs that never stamped one, the start) is older than
    ``RUN_COLGADO_TRAS`` — a run that is merely slow keeps its heartbeat fresh."""
    ahora = ahora or datetime.now(timezone.utc)
    limite = ahora - RUN_COLGADO_TRAS
    colgados = db.execute(
        select(ScrapingRun).where(
            ScrapingRun.status == "running",
            func.coalesce(ScrapingRun.heartbeat_at, ScrapingRun.started_at) < limite,
        )
    ).scalars().all()
    for run in colgados:
        run.status = "failed"
        run.fase = "fallido"
        run.error_log = "Ejecución interrumpida (el worker se detuvo antes de terminar)."
        run.finished_at = ahora
    if colgados:
        db.commit()
    return len(colgados)


def fechas_pendientes(db, *, hoy: date | None = None, dias: int = CATCH_UP_DIAS) -> list[date]:
    """Dates in the last ``dias`` days (today included, Sundays excluded —
    the BOE has no Sunday edition) without a completed daily run."""
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=dias - 1)
    completadas = set(
        db.execute(
            select(ScrapingRun.fecha_boe).where(
                ScrapingRun.fecha_boe >= desde, ScrapingRun.fecha_boe <= hoy,
                ScrapingRun.status == "completed", ScrapingRun.tipo == "diario",
            ).distinct()
        ).scalars().all()
    )
    return [
        desde + timedelta(days=offset)
        for offset in range(dias)
        if (desde + timedelta(days=offset)) not in completadas and (desde + timedelta(days=offset)).weekday() != 6
    ]


def fechas_con_extraccion_pendiente(db, *, hoy: date | None = None, dias: int = CATCH_UP_DIAS) -> list[date]:
    """Dates in the window that completed a run but still have documents whose
    extraction is due (a day cut short by the per-run cap, an OpenAI outage…)."""
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=dias - 1)
    return list(
        db.execute(
            select(BoeDocumento.fecha_publicacion).where(
                BoeDocumento.fecha_publicacion >= desde, BoeDocumento.fecha_publicacion <= hoy,
                BoeDocumento.extraction_status.in_(("pending", "error")),
                BoeDocumento.extraction_intentos < MAX_INTENTOS_CON_ESPERA,
                (BoeDocumento.source.is_(None)) | (BoeDocumento.source != "manual"),
            ).distinct().order_by(BoeDocumento.fecha_publicacion)
        ).scalars().all()
    )


@celery.task(name="app.tasks.scraping.run_daily_scraping")
def run_daily_scraping(fecha_str: str | None = None, force: bool = False, permitir_extraccion_pago: bool | None = None, modo_extraccion: str | None = None) -> dict:
    """Scheduled entry point. With no explicit flag the runtime configuration
    decides whether OpenAI runs (see ``run_scraping``)."""
    return run_scraping(fecha_str, force, permitir_extraccion_pago, modo_extraccion=modo_extraccion)


@celery.task(name="app.tasks.scraping.catch_up_scraping")
def catch_up_scraping(dias: int = CATCH_UP_DIAS) -> dict:
    """Queue a run for every recent date without a completed run or with
    extraction still due (a laptop that was off, a failed morning attempt),
    newest first: yesterday's calls matter more than last week's. Each queued
    run is itself idempotent and incremental, so over-queueing is harmless."""
    db = SyncSessionLocal()
    try:
        colgados = marcar_runs_colgados(db)
        pendientes = set(fechas_pendientes(db, dias=dias))
        config = leer_configuracion(db)
        if _extraccion_automatica_permitida(config):
            pendientes.update(fechas_con_extraccion_pendiente(db, dias=dias))
    finally:
        db.close()
    ordenadas = sorted(pendientes, reverse=True)
    for fecha in ordenadas:
        run_daily_scraping.delay(fecha.isoformat())
    logger.info("Catch-up: %d fechas encoladas (%s), %d runs colgados marcados", len(ordenadas), ordenadas, colgados)
    return {"encoladas": [f.isoformat() for f in ordenadas], "runs_colgados": colgados}


@worker_ready.connect
def _al_arrancar_worker(sender=None, **_kwargs) -> None:
    """The moment the worker is up, check today (and the last few days): the
    operator expects the day's sanctions to appear when the software is
    started, not at the next scheduled slot."""
    try:
        catch_up_scraping.apply_async(countdown=15)
        # Free: index anything downloaded before the historical index existed
        # (or whose indexing failed) so "Consulta por DNI/CIF" sees it.
        from app.tasks.historico_reindexado import reindexar_task

        reindexar_task.apply_async(countdown=30)
    except Exception:  # pragma: no cover - broker down at startup
        logger.exception("No se pudo encolar el catch-up inicial")
