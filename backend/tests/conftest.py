from __future__ import annotations

import pytest
from sqlalchemy import text

from app.database import SyncSessionLocal


@pytest.fixture
def clean_database():
    """Tests run only against docker-compose.test.yml's ephemeral database."""
    session = SyncSessionLocal()
    try:
        for table in ("notificaciones", "seguimientos", "sancionados", "boe_documentos", "scraping_runs", "codigo_oportunidad_contadores"):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
        yield
    finally:
        session.close()
