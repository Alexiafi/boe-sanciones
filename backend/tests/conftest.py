from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.database import SyncSessionLocal, async_engine
from app.services import extractor as extractor_module

# NOTE: there is deliberately no blanket "ban httpx.Client everywhere" fixture
# here. httpx.Client() does not open a socket at construction time (it's a
# lazy connection pool), and the existing enrichment tests construct one
# legitimately (enrichment enabled + fixture provider) while mocking the
# actual request-making call (_fetch/_robots_allows) deeper in the cascade.
# Each module that must prove it NEVER reaches the network when disabled
# does so locally with its own monkeypatch of httpx.Client to a raising fake
# (see test_enrichment.py's "..._never_constructs_http_client" tests and
# test_historico_teu.py) — that per-test discipline is what's load-bearing,
# not a global trap that would also catch legitimate enabled-path requests.


@pytest.fixture(autouse=True)
def _sin_openai(monkeypatch):
    """No test may construct a real OpenAI client. Tests that exercise
    extraction inject a fake extractor/OpenAI stand-in explicitly."""

    def _boom(*args, **kwargs):
        raise AssertionError("Ningún test puede construir un cliente OpenAI real")

    monkeypatch.setattr(extractor_module, "OpenAI", _boom)


@pytest.fixture(autouse=True)
def _dispose_async_engine_after_test():
    """Avoid asyncpg connections leaking across event loops.

    Each ``with TestClient(app) as client`` spins up its own anyio event loop.
    The module-level ``async_engine`` pools connections, so a connection opened
    under one test's loop can be handed to the next test's (different) loop and
    asyncpg raises "attached to a different loop". Disposing the pool after every
    test forces the next TestClient to open fresh connections on its own loop.
    """
    yield
    asyncio.run(async_engine.dispose())


@pytest.fixture
def clean_database():
    """Tests run only against docker-compose.test.yml's ephemeral database."""
    session = SyncSessionLocal()
    try:
        # sancionados.cliente_id and clientes.sancion_origen_id form a cycle
        # between the two tables; null out the pointer from sancionados first
        # so clientes (and everything hanging off it) can be deleted before
        # sancionados itself, without hitting either FK constraint.
        session.execute(text("UPDATE sancionados SET cliente_id = NULL"))
        for table in (
            "documentos_comerciales", "contadores_factura",
            "historico_resultados", "historico_backfill_runs",
            "acciones_agendadas", "actividades_cliente", "notas_cliente", "clientes",
            "codigo_cliente_contadores",
            "enriquecimiento_intentos", "enriquecimiento_cache",
            "notificaciones", "seguimientos", "sancionados", "boe_documentos",
            "historico_docs",
            "scraping_runs", "codigo_oportunidad_contadores",
        ):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
        yield
    finally:
        session.close()
