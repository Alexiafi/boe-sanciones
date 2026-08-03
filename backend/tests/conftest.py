from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.database import SyncSessionLocal, async_engine


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
            "acciones_agendadas", "actividades_cliente", "notas_cliente", "clientes",
            "codigo_cliente_contadores",
            "enriquecimiento_intentos", "enriquecimiento_cache",
            "notificaciones", "seguimientos", "sancionados", "boe_documentos",
            "scraping_runs", "codigo_oportunidad_contadores",
        ):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
        yield
    finally:
        session.close()
