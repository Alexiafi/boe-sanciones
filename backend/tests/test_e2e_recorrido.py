"""End-to-end walkthrough with simulated data, entirely local and free:

    oportunidad -> convertir en cliente -> histórico (indexado simulado,
    búsqueda) -> extracción on-demand (extractor falso) -> contrato + factura
    (PDF real, motor local) -> intento de envío (rechazado: EMAIL_SENDING
    sigue apagado por defecto).

No network, no OpenAI, no SMTP real anywhere in this test. Deliberately uses
a SINGLE ``with TestClient(app) as client:`` block for every HTTP call: each
block spins up its own anyio event loop (see conftest.py's
``_dispose_async_engine_after_test``), and opening a second one mid-test
while the async engine's pool still holds a connection from the first raises
asyncpg's "attached to a different loop" — the sync setup steps in between
use SyncSessionLocal directly and don't need their own TestClient block.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SyncSessionLocal
from app.main import app
from app.models.documento import BoeDocumento
from app.models.historico import HistoricoResultado
from app.models.sancionado import Sancionado
from app.services.historico.indexado import upsert_historico_doc
from app.services.historico.patterns import extraer_claves
from app.services.oportunidades import allocate_codigo
from app.tasks.historico_extraccion import ExtraccionHistoricaDependencies, extraer_historico

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _crear_oportunidad_simulada() -> int:
    session = SyncSessionLocal()
    try:
        documento = BoeDocumento(boe_id="BOE-E2E-1", fecha_publicacion=date(2026, 8, 1), titulo="Sanción E2E")
        session.add(documento)
        session.flush()
        sancionado = Sancionado(
            boe_document_id=documento.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="nueva",
            origen_clave="e2e-clave-1", nombre="Recorrido E2E SL", tipo_persona="juridica",
            identificador="B12345674", tipo_identificador="CIF", importe_multa_eur=500,
        )
        session.add(sancionado)
        session.commit()
        return sancionado.id
    finally:
        session.close()


def _indexar_documento_historico_simulado() -> None:
    session = SyncSessionLocal()
    try:
        texto = "Sancionada RECORRIDO E2E SL con CIF B12345674 por infracción muy grave en 2023."
        claves = extraer_claves(texto, "Expediente sancionador histórico")
        upsert_historico_doc(
            session, boe_id="BOE-E2E-HIST-1", fuente="boe", fecha_publicacion=date(2023, 5, 1),
            titulo="Expediente sancionador histórico", origen_indexado="backfill", texto=texto, claves=claves,
        )
        session.commit()
    finally:
        session.close()


@pytest.mark.integration
def test_recorrido_completo_oportunidad_a_documentos(monkeypatch, tmp_path, clean_database):
    # 1. Simulate the daily pipeline having already created an opportunity.
    sancionado_id = _crear_oportunidad_simulada()

    monkeypatch.setattr(settings, "emisor_nombre", "Despacho Judit SL")
    monkeypatch.setattr(settings, "emisor_cif", "B99999999")
    monkeypatch.setattr(settings, "emisor_direccion", "Gran Vía 1, Madrid")
    monkeypatch.setattr(settings, "factura_serie", "FAC")
    monkeypatch.setattr(settings, "documentos_dir", str(tmp_path))

    with TestClient(app) as client:
        # 2. Convert opportunity -> client.
        resp = client.post(f"/api/sanciones/{sancionado_id}/convertir")
        assert resp.status_code == 200, resp.text
        cliente_id = resp.json()["cliente"]["id"]
        assert resp.json()["created"] is True

        # Idempotent: converting again returns the same client.
        resp2 = client.post(f"/api/sanciones/{sancionado_id}/convertir")
        assert resp2.json()["created"] is False
        assert resp2.json()["cliente"]["id"] == cliente_id

        # 3. Simulate historical accumulation: a document mentioning this
        # client's CIF, indexed the same way the daily pipeline/backfill
        # would (regex-only, no LLM) — plain sync DB work, no HTTP involved.
        _indexar_documento_historico_simulado()

        # 4. Search the client's history.
        resp = client.post(f"/api/clientes/{cliente_id}/historico/buscar", json={"incluir_teu": False})
        assert resp.status_code == 200, resp.text
        resultados = resp.json()["resultados"]
        assert len(resultados) == 1
        assert resultados[0]["via_match"] == "cif"
        resultado_id = resultados[0]["id"]

        # 5. On-demand extraction with a FAKE extractor (mocked, zero cost) —
        # calling the sync function directly rather than through Celery,
        # since this test compose has no broker (same discipline as
        # test_api_*.py's Celery-adjacent tests).
        from app.services.extractor import AfectadoExtraido, ResultadoExtraccion

        def extractor_falso(texto, titulo):
            return ResultadoExtraccion(
                es_documento_relevante=True,
                afectados=[AfectadoExtraido(nombre="Recorrido E2E SL", identificador="B12345674", importe_multa_eur=300)],
            )

        monkeypatch.setattr(settings, "openai_extraction_enabled", True)
        monkeypatch.setattr(settings, "openai_api_key", "fake-key-not-used")
        resultado_extraccion = extraer_historico(
            [resultado_id], permitir_extraccion_pago=True,
            dependencies=ExtraccionHistoricaDependencies(extractor=extractor_falso),
        )
        assert resultado_extraccion["extraidos"] == 1

        session = SyncSessionLocal()
        try:
            row = session.get(HistoricoResultado, resultado_id)
            assert row.extraido is True
            assert row.datos_extraidos["afectados"][0]["nombre"] == "Recorrido E2E SL"
        finally:
            session.close()

        # 6. Commercial documents: emisor already configured above (as Judit
        # would via .env); generate a real, local, zero-cost PDF for both.
        client.patch(f"/api/clientes/{cliente_id}", json={"direccion_fiscal": "Calle Falsa 1, Madrid"})

        resp_validar = client.get(f"/api/clientes/{cliente_id}/documentos/validar", params={"tipo": "contrato"})
        assert resp_validar.status_code == 200
        assert resp_validar.json()["listo"] is True

        resp_contrato = client.post(f"/api/clientes/{cliente_id}/contrato", json={"precio": 1200.0})
        assert resp_contrato.status_code == 200, resp_contrato.text
        documento_contrato = resp_contrato.json()
        assert documento_contrato["tipo"] == "contrato"

        resp_factura = client.post(
            f"/api/clientes/{cliente_id}/factura", json={"cuantia": 250.0, "concepto": "Gestión del expediente"}
        )
        assert resp_factura.status_code == 200, resp_factura.text
        documento_factura = resp_factura.json()
        assert documento_factura["numero"].startswith("FAC-")

        resp_docs = client.get(f"/api/clientes/{cliente_id}/documentos")
        assert len(resp_docs.json()) == 2

        # 7. Sending stays blocked: EMAIL_SENDING_ENABLED is still false, so
        # even a "prepared" send attempt is refused, never a real email.
        resp_enviar = client.post(
            f"/api/documentos-comerciales/{documento_factura['id']}/enviar",
            json={"confirmar": True},
        )
        assert resp_enviar.status_code == 409

        # 8. The client's activity timeline reflects every step.
        resp_actividad = client.get(f"/api/clientes/{cliente_id}/actividad")
        tipos = [a["tipo"] for a in resp_actividad.json()]
        assert "conversion" in tipos
        assert "sistema" in tipos  # contract/invoice generation + extraction
