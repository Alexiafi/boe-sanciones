"""OpenAI Batch API mode: request building, output parsing, submission from
the daily pipeline and the historical extraction, and result application.

No test here touches the network: the transport is a fake that records
what was uploaded and returns canned JSONL, and the autouse fixture in
conftest.py makes constructing a real OpenAI client an assertion error.
"""

from __future__ import annotations

import json
import os
from datetime import date

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.cliente import Cliente
from app.models.documento import BoeDocumento
from app.models.extraccion_batch import ExtraccionBatch, ExtraccionBatchItem
from app.models.historico import HistoricoResultado
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.services import openai_batch
from app.services.configuracion import ConfiguracionRuntime, ConfiguracionUpdate, guardar_configuracion
from app.services.extractor import AfectadoExtraido, ResultadoExtraccion, build_extraction_request, parse_extraction_response
from app.services.historico.indexado import upsert_historico_doc
from app.services.openai_batch import EstadoBatchRemoto, PeticionBatch, construir_jsonl, enviar_batch, parsear_salida
from app.services.oportunidades import allocate_codigo
from app.tasks import extraccion_batch, historico_extraccion, scraping

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


# --- fakes ------------------------------------------------------------------

def _respuesta(afectados: list[dict], relevante: bool = True) -> dict:
    """A chat-completion body exactly as OpenAI returns it inside a batch line."""
    contenido = json.dumps({"afectados": afectados, "resumen": None, "es_documento_relevante": relevante})
    return {"choices": [{"message": {"role": "assistant", "content": contenido, "refusal": None}}]}


def _linea(custom_id: str, body: dict | None = None, *, error: str | None = None, status_code: int = 200) -> str:
    if error:
        return json.dumps({"custom_id": custom_id, "response": None, "error": {"message": error}})
    return json.dumps({"custom_id": custom_id, "response": {"status_code": status_code, "body": body}, "error": None})


class FakeTransport:
    """Records uploads and serves scripted statuses/outputs."""

    def __init__(self, *, fallo_envio: bool = False) -> None:
        self.subidos: list[tuple[str, bytes]] = []
        self.batches: dict[str, dict] = {}
        self.estados: dict[str, EstadoBatchRemoto] = {}
        self.ficheros: dict[str, str] = {}
        self.fallo_envio = fallo_envio
        self.consultas = 0

    def subir_jsonl(self, contenido: bytes, nombre: str) -> str:
        if self.fallo_envio:
            raise RuntimeError("upload rechazado")
        self.subidos.append((nombre, contenido))
        return f"file-{len(self.subidos)}"

    def crear_batch(self, input_file_id: str, metadata: dict[str, str]) -> tuple[str, EstadoBatchRemoto]:
        batch_id = f"batch_{len(self.batches) + 1}"
        self.batches[batch_id] = {"input_file_id": input_file_id, "metadata": metadata}
        self.estados[batch_id] = EstadoBatchRemoto(status="en_progreso")
        return batch_id, self.estados[batch_id]

    def consultar(self, batch_id: str) -> EstadoBatchRemoto:
        self.consultas += 1
        return self.estados[batch_id]

    def descargar(self, file_id: str) -> str:
        return self.ficheros[file_id]

    # helpers for tests
    def completar(self, batch_id: str, lineas: list[str], *, status: str = "completado", errores: list[str] | None = None) -> None:
        self.ficheros[f"out-{batch_id}"] = "\n".join(lineas) + "\n"
        error_file = None
        if errores:
            error_file = f"err-{batch_id}"
            self.ficheros[error_file] = "\n".join(errores) + "\n"
        self.estados[batch_id] = EstadoBatchRemoto(
            status=status, output_file_id=f"out-{batch_id}", error_file_id=error_file,
            completados=len(lineas), fallidos=len(errores or []), total=len(lineas) + len(errores or []),
        )

    def custom_ids_enviados(self) -> list[str]:
        ids = []
        for _nombre, contenido in self.subidos:
            for raw in contenido.decode("utf-8").splitlines():
                if raw.strip():
                    ids.append(json.loads(raw)["custom_id"])
        return ids


def _deps_pipeline(documents: list[dict], transport: FakeTransport, *, config: ConfiguracionRuntime, extractor=None):
    return scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documents,
        fetch_text=lambda d: (f"texto de {d['identificador']}", "xml", None),
        extractor=extractor or (lambda *_: (_ for _ in ()).throw(AssertionError("real-time extractor must not run in batch mode"))),
        send_digest=lambda *_: None, notify=scraping.create_inapp_notification,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
        batch_transport=lambda: transport, leer_configuracion=lambda _db: config,
    )


def _habilitar_openai(monkeypatch) -> None:
    monkeypatch.setattr(settings, "openai_extraction_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))


# --- pure helpers -----------------------------------------------------------

def test_build_request_shares_prompt_and_schema_and_omits_temperature_for_gpt5():
    body = build_extraction_request("texto", "titulo", model="gpt-5.4-mini")
    assert body["model"] == "gpt-5.4-mini"
    assert body["messages"][0]["role"] == "system"
    assert "TÍTULO DEL DOCUMENTO BOE:\ntitulo" in body["messages"][1]["content"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "temperature" not in body
    legacy = build_extraction_request("texto", "titulo", model="gpt-4.1-mini")
    assert legacy["temperature"] == 0.0


def test_construir_jsonl_one_line_per_document_with_custom_id():
    contenido = construir_jsonl([
        PeticionBatch(custom_id="doc-1", texto="a", titulo="A", boe_document_id=1),
        PeticionBatch(custom_id="doc-2", texto="b", titulo="B", boe_document_id=2),
    ], model="gpt-5.4-mini")
    lineas = [json.loads(l) for l in contenido.decode("utf-8").splitlines()]
    assert [l["custom_id"] for l in lineas] == ["doc-1", "doc-2"]
    assert all(l["url"] == "/v1/chat/completions" and l["method"] == "POST" for l in lineas)
    assert lineas[0]["body"]["model"] == "gpt-5.4-mini"


def test_parse_response_and_parsear_salida():
    body = _respuesta([{"nombre": "Acme SL", "identificador": "B12345678"}])
    resultado = parse_extraction_response(body)
    assert resultado.afectados[0].identificador == "B12345678"
    with pytest.raises(ValueError):
        parse_extraction_response({"choices": [{"message": {"refusal": "no"}}]})

    salida = parsear_salida("\n".join([
        _linea("doc-1", body), _linea("doc-2", None, error="rate limited"),
        _linea("doc-3", {"error": {"message": "bad request"}}, status_code=400), "not json",
    ]))
    assert salida["doc-1"].body == body and salida["doc-1"].error is None
    assert salida["doc-2"].error == "rate limited"
    assert salida["doc-3"].error == "bad request"
    assert "not json" not in salida


# --- submission --------------------------------------------------------------

@pytest.mark.integration
def test_enviar_batch_persists_rows_and_marks_fallido_on_transport_error(clean_database):
    session = SyncSessionLocal()
    try:
        doc = BoeDocumento(boe_id="BOE-BATCH-ENV", fecha_publicacion=date(2026, 9, 1), titulo="T", texto_plano="x")
        session.add(doc)
        session.flush()
        peticiones = [PeticionBatch(custom_id=f"doc-{doc.id}", texto="x", titulo="T", boe_document_id=doc.id)]

        ok = FakeTransport()
        batch = enviar_batch(session, tipo="diario", peticiones=peticiones, transport=ok)
        session.commit()
        assert batch.status == "enviado" and batch.openai_batch_id == "batch_1" and batch.total_items == 1
        assert ok.batches["batch_1"]["metadata"]["tipo"] == "diario"
        assert session.execute(select(ExtraccionBatchItem).where(ExtraccionBatchItem.batch_id == batch.id)).scalars().one().custom_id == f"doc-{doc.id}"

        with pytest.raises(RuntimeError):
            enviar_batch(session, tipo="diario", peticiones=peticiones, transport=FakeTransport(fallo_envio=True))
        session.commit()
        fallido = session.execute(select(ExtraccionBatch).where(ExtraccionBatch.status == "fallido")).scalars().one()
        assert "upload rechazado" in (fallido.error_log or "")
    finally:
        session.close()


@pytest.mark.integration
def test_pipeline_batch_mode_queues_documents_instead_of_calling_openai(monkeypatch, clean_database):
    _habilitar_openai(monkeypatch)
    documents = [
        {"identificador": "BOE-2026-B1", "fecha_publicacion": date(2026, 9, 1), "titulo": "Doc 1", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-B2", "fecha_publicacion": date(2026, 9, 1), "titulo": "Doc 2", "seccion_codigo": "3"},
    ]
    transport = FakeTransport()
    config = ConfiguracionRuntime(extraccion_modo="batch", extraccion_max_docs_por_ejecucion=10)
    result = scraping.run_scraping("2026-09-01", permitir_extraccion_pago=True, dependencies=_deps_pipeline(documents, transport, config=config))
    assert result["modo_extraccion"] == "batch"
    assert result["batch_enviados"] == 2 and result["extracted"] == 0 and result["openai_calls"] == 2
    assert len(transport.custom_ids_enviados()) == 2

    session = SyncSessionLocal()
    try:
        docs = session.execute(select(BoeDocumento).order_by(BoeDocumento.boe_id)).scalars().all()
        assert [d.extraction_status for d in docs] == ["batch_pending", "batch_pending"]
        batch = session.execute(select(ExtraccionBatch)).scalars().one()
        assert batch.status == "enviado" and batch.tipo == "diario" and batch.scraping_run_id is not None
        run = session.execute(select(scraping.ScrapingRun)).scalars().one()
        assert run.extraction_provider == "openai_batch" and run.status == "completed"
    finally:
        session.close()

    # A second run for the same day must not re-queue documents already in flight.
    again = scraping.run_scraping("2026-09-01", permitir_extraccion_pago=True, force=False, dependencies=_deps_pipeline(documents, transport, config=config))
    assert again.get("skipped") is True
    assert len(transport.subidos) == 1
    # Not even a forced run: the batch is still open at OpenAI, re-queueing would pay twice.
    forced = scraping.run_scraping("2026-09-01", permitir_extraccion_pago=True, force=True, dependencies=_deps_pipeline(documents, transport, config=config))
    assert forced.get("batch_enviados") is None and forced["openai_calls"] == 0
    assert len(transport.subidos) == 1


@pytest.mark.integration
def test_pipeline_batch_submission_failure_marks_documents_error_but_run_completes(monkeypatch, clean_database):
    _habilitar_openai(monkeypatch)
    documents = [{"identificador": "BOE-2026-BF", "fecha_publicacion": date(2026, 9, 2), "titulo": "Doc", "seccion_codigo": "3"}]
    transport = FakeTransport(fallo_envio=True)
    config = ConfiguracionRuntime(extraccion_modo="batch")
    result = scraping.run_scraping("2026-09-02", permitir_extraccion_pago=True, dependencies=_deps_pipeline(documents, transport, config=config))
    assert result["errors"] == 1 and "batch_id" not in result
    session = SyncSessionLocal()
    try:
        doc = session.execute(select(BoeDocumento)).scalars().one()
        assert doc.extraction_status == "error" and "Batch" in (doc.extraction_error or "")
        run = session.execute(select(scraping.ScrapingRun)).scalars().one()
        assert run.status == "completed" and run.errors == 1
        assert session.execute(select(ExtraccionBatch)).scalars().one().status == "fallido"
    finally:
        session.close()


# --- polling / application ---------------------------------------------------

@pytest.mark.integration
def test_procesar_batches_applies_results_like_real_time(monkeypatch, clean_database):
    """Completed batch → opportunities + notification + client auto-assignment,
    exactly what the real-time path produces; a per-line error marks only that
    document; a second poll is a no-op."""
    _habilitar_openai(monkeypatch)
    session = SyncSessionLocal()
    try:
        origen = BoeDocumento(boe_id="BOE-CLI-ORIGEN", fecha_publicacion=date(2026, 1, 1), titulo="Origen")
        session.add(origen)
        session.flush()
        sancionado_origen = Sancionado(
            boe_document_id=origen.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
            origen_clave="origen-cliente", nombre="Acme SL",
        )
        session.add(sancionado_origen)
        session.flush()
        cliente = Cliente(codigo="CLI-2026-0001", nombre_razon_social="Acme SL", cif_nif="B12345678", sancion_origen_id=sancionado_origen.id)
        session.add(cliente)
        session.commit()
        cliente_id = cliente.id
    finally:
        session.close()

    documents = [
        {"identificador": "BOE-2026-P1", "fecha_publicacion": date(2026, 9, 3), "titulo": "Doc 1", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-P2", "fecha_publicacion": date(2026, 9, 3), "titulo": "Doc 2", "seccion_codigo": "3"},
        {"identificador": "BOE-2026-P3", "fecha_publicacion": date(2026, 9, 3), "titulo": "Doc 3", "seccion_codigo": "3"},
    ]
    transport = FakeTransport()
    config = ConfiguracionRuntime(extraccion_modo="batch")
    scraping.run_scraping("2026-09-03", permitir_extraccion_pago=True, dependencies=_deps_pipeline(documents, transport, config=config))

    session = SyncSessionLocal()
    try:
        ids = {d.boe_id: d.id for d in session.execute(select(BoeDocumento)).scalars().all()}
    finally:
        session.close()

    deps = extraccion_batch.BatchDependencies(transport=lambda: transport, send_digest=lambda *_: None)
    # Still in progress: nothing applied.
    primero = extraccion_batch.procesar_batches_pendientes(deps)
    assert primero == {"revisados": 1, "finalizados": 0, "sancionados": 0, "errores": 0}

    transport.completar("batch_1", [
        _linea(f"doc-{ids['BOE-2026-P1']}", _respuesta([
            {"nombre": "Acme SL", "identificador": "B12345678", "importe_multa_eur": 300},
            {"nombre": "Otro", "identificador": "12345678Z"},
        ])),
        _linea(f"doc-{ids['BOE-2026-P3']}", _respuesta([], relevante=False)),
    ], errores=[_linea(f"doc-{ids['BOE-2026-P2']}", None, error="context length exceeded")])

    resumen = extraccion_batch.procesar_batches_pendientes(deps)
    assert resumen["finalizados"] == 1 and resumen["sancionados"] == 2 and resumen["errores"] == 1

    session = SyncSessionLocal()
    try:
        batch = session.execute(select(ExtraccionBatch)).scalars().one()
        assert batch.status == "completado" and batch.completados == 2 and batch.errores == 1 and batch.sancionados_creados == 2
        estados = {d.boe_id: d.extraction_status for d in session.execute(select(BoeDocumento)).scalars().all()}
        assert estados["BOE-2026-P1"] == "completed" and estados["BOE-2026-P3"] == "completed"
        assert estados["BOE-2026-P2"] == "error"
        nuevos = session.execute(select(Sancionado).where(Sancionado.origen_clave != "origen-cliente")).scalars().all()
        assert {s.identificador for s in nuevos} == {"B12345678", "12345678Z"}
        acme = next(s for s in nuevos if s.identificador == "B12345678")
        assert acme.cliente_id == cliente_id and acme.estado_oportunidad == "cliente"
        notifs = session.execute(select(Notificacion)).scalars().all()
        assert any(n.cliente_id == cliente_id and n.tipo == "nueva_sancion_cliente" for n in notifs)
        # One alert per new sanction: the client's raised once, under the
        # client's name (it used to be announced twice, first as a bare CIF).
        assert sum(1 for n in notifs if n.tipo == "nueva_sancion") == 1
        assert sum(1 for n in notifs if n.tipo == "nueva_sancion_cliente") == 1
        cliente_notif = next(n for n in notifs if n.tipo == "nueva_sancion_cliente")
        assert "Acme SL" in cliente_notif.titulo
    finally:
        session.close()

    # Terminal batches are not polled again, and re-applying cannot duplicate.
    consultas = transport.consultas
    assert extraccion_batch.procesar_batches_pendientes(deps)["revisados"] == 0
    assert transport.consultas == consultas


@pytest.mark.integration
def test_expired_batch_marks_missing_items_as_error(monkeypatch, clean_database):
    _habilitar_openai(monkeypatch)
    documents = [{"identificador": "BOE-2026-EXP", "fecha_publicacion": date(2026, 9, 4), "titulo": "Doc", "seccion_codigo": "3"}]
    transport = FakeTransport()
    scraping.run_scraping("2026-09-04", permitir_extraccion_pago=True, dependencies=_deps_pipeline(documents, transport, config=ConfiguracionRuntime(extraccion_modo="batch")))
    transport.completar("batch_1", [], status="expirado")
    deps = extraccion_batch.BatchDependencies(transport=lambda: transport, send_digest=lambda *_: None)
    extraccion_batch.procesar_batches_pendientes(deps)
    session = SyncSessionLocal()
    try:
        batch = session.execute(select(ExtraccionBatch)).scalars().one()
        assert batch.status == "expirado" and batch.errores == 1
        doc = session.execute(select(BoeDocumento)).scalars().one()
        assert doc.extraction_status == "error" and "expirado" in (doc.extraction_error or "")
    finally:
        session.close()

    # A forced re-run re-queues the errored document in a fresh batch.
    scraping.run_scraping("2026-09-04", permitir_extraccion_pago=True, force=True, dependencies=_deps_pipeline(documents, transport, config=ConfiguracionRuntime(extraccion_modo="batch")))
    assert len(transport.subidos) == 2


@pytest.mark.integration
def test_historico_extraction_in_batch_mode(monkeypatch, clean_database):
    _habilitar_openai(monkeypatch)
    session = SyncSessionLocal()
    try:
        origen = BoeDocumento(boe_id="BOE-H-ORIGEN", fecha_publicacion=date(2026, 1, 1), titulo="Origen")
        session.add(origen)
        session.flush()
        sancionado = Sancionado(boe_document_id=origen.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente", origen_clave="origen-h", nombre="Acme SL")
        session.add(sancionado)
        session.flush()
        cliente = Cliente(codigo="CLI-2026-0002", nombre_razon_social="Acme SL", cif_nif="B12345678", sancion_origen_id=sancionado.id)
        session.add(cliente)
        session.flush()
        doc, _ = upsert_historico_doc(
            session, boe_id="BOE-H-1", fuente="boe", fecha_publicacion=date(2025, 5, 5), titulo="Histórico",
            origen_indexado="backfill", texto="Sancionada ACME SL con CIF B12345678", guardar_texto=True,
        )
        resultado = HistoricoResultado(cliente_id=cliente.id, historico_doc_id=doc.id, score=1.0, via_match="cif")
        session.add(resultado)
        session.commit()
        resultado_id = resultado.id
    finally:
        session.close()

    transport = FakeTransport()
    deps = historico_extraccion.ExtraccionHistoricaDependencies(
        extractor=lambda *_: (_ for _ in ()).throw(AssertionError("no real-time")),
        batch_transport=lambda: transport,
        leer_configuracion=lambda _db: ConfiguracionRuntime(historico_extraccion_modo="batch"),
    )
    resumen = historico_extraccion.extraer_historico([resultado_id], permitir_extraccion_pago=True, dependencies=deps)
    assert resumen["modo"] == "batch" and resumen["en_batch"] == 1 and resumen["extraidos"] == 0
    assert transport.custom_ids_enviados() == [f"hist-{resultado_id}"]

    transport.completar("batch_1", [_linea(f"hist-{resultado_id}", _respuesta([{"nombre": "Acme SL", "identificador": "B12345678", "importe_multa_eur": 99}]))])
    extraccion_batch.procesar_batches_pendientes(extraccion_batch.BatchDependencies(transport=lambda: transport, send_digest=lambda *_: None))

    session = SyncSessionLocal()
    try:
        resultado = session.get(HistoricoResultado, resultado_id)
        assert resultado.extraido is True
        assert resultado.datos_extraidos["afectados"][0]["importe_multa_eur"] == 99
        assert resultado.extractor_version.startswith("openai-batch:")
        batch = session.execute(select(ExtraccionBatch)).scalars().one()
        assert batch.tipo == "historico_cliente" and batch.status == "completado" and batch.completados == 1
    finally:
        session.close()


# --- runtime configuration ---------------------------------------------------

@pytest.mark.integration
def test_scheduled_run_follows_runtime_configuration(monkeypatch, clean_database):
    """``permitir_extraccion_pago=None`` (what Celery beat passes) extracts
    only when the runtime config says so AND the .env gates are open."""
    _habilitar_openai(monkeypatch)
    documents = [{"identificador": "BOE-2026-CFG", "fecha_publicacion": date(2026, 9, 5), "titulo": "Doc", "seccion_codigo": "3"}]
    calls: list[str] = []

    def extractor(text, title):
        calls.append(title)
        return ResultadoExtraccion(afectados=[AfectadoExtraido(identificador="B00000000", nombre="X")])

    transport = FakeTransport()
    session = SyncSessionLocal()
    try:
        guardar_configuracion(session, ConfiguracionUpdate(extraccion_automatica=False))
        session.commit()
    finally:
        session.close()

    deps = _deps_pipeline(documents, transport, config=ConfiguracionRuntime(extraccion_automatica=False), extractor=extractor)
    off = scraping.run_scraping("2026-09-05", permitir_extraccion_pago=None, dependencies=deps)
    assert off["modo_extraccion"] == "sin_extraccion" and calls == [] and off["extracted"] == 0

    deps = _deps_pipeline(documents, transport, config=ConfiguracionRuntime(extraccion_automatica=True, extraccion_modo="tiempo_real"), extractor=extractor)
    on = scraping.run_scraping("2026-09-05", permitir_extraccion_pago=None, dependencies=deps)
    assert on["modo_extraccion"] == "tiempo_real" and calls == ["Doc"] and on["extracted"] == 1

    # Gates closed in .env: the scheduled run must degrade to indexing, never raise.
    monkeypatch.setattr(settings, "openai_extraction_enabled", False)
    quiet = scraping.run_scraping("2026-09-05", permitir_extraccion_pago=None, force=True, dependencies=deps)
    assert quiet["modo_extraccion"] == "sin_extraccion" and len(calls) == 1


@pytest.mark.integration
def test_default_transport_is_never_built_in_real_time_mode(monkeypatch, clean_database):
    """Real-time mode must not construct the batch transport (and therefore
    never an OpenAI client for batches)."""
    _habilitar_openai(monkeypatch)
    monkeypatch.setattr(openai_batch, "OpenAIBatchTransport", lambda *a, **k: (_ for _ in ()).throw(AssertionError("transport built")))
    documents = [{"identificador": "BOE-2026-RT", "fecha_publicacion": date(2026, 9, 6), "titulo": "Doc", "seccion_codigo": "3"}]
    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: documents, fetch_text=lambda _: ("texto", "xml", None),
        extractor=lambda *_: ResultadoExtraccion(afectados=[]), send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
        leer_configuracion=lambda _db: ConfiguracionRuntime(extraccion_modo="tiempo_real"),
    )
    result = scraping.run_scraping("2026-09-06", permitir_extraccion_pago=True, dependencies=deps)
    assert result["openai_calls"] == 1 and "batch_id" not in result
