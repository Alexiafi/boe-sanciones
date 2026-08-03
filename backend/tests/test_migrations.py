from __future__ import annotations

from pathlib import Path
import os

import pytest

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import sync_engine
from scripts import migrate

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", os.environ["TEST_DATABASE_URL_SYNC"])
    return config


@pytest.mark.integration
def test_migrations_reach_opportunity_head(clean_database):
    inspector = inspect(sync_engine)
    assert {"boe_documentos", "sancionados", "codigo_oportunidad_contadores", "alembic_version"}.issubset(set(inspector.get_table_names()))
    columns = {column["name"] for column in inspector.get_columns("sancionados")}
    assert {"codigo", "estado_oportunidad", "origen_clave", "importe_deuda_eur", "contacto_estado"}.issubset(columns)
    revisions = Path("alembic/versions")
    assert (revisions / "0001_legacy_baseline.py").exists()
    assert (revisions / "0002_opportunity_core.py").exists()
    assert (revisions / "0003_enrichment_core.py").exists()
    assert (revisions / "0004_clientes_crm.py").exists()


@pytest.mark.integration
def test_bootstrap_empty_and_legacy_schema_preserves_duplicate_rows():
    config = _alembic_config()
    command.downgrade(config, "base")
    migrate.main()

    # Recreate the exact unversioned legacy state, including a prior duplicate.
    command.downgrade(config, "0001_legacy_baseline")
    with sync_engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        document_id = connection.execute(
            text("""
                INSERT INTO boe_documentos (boe_id, fecha_publicacion, titulo)
                VALUES ('BOE-2025-LEGACY', '2025-01-02', 'Documento legado')
                RETURNING id
            """)
        ).scalar_one()
        for _ in range(2):
            connection.execute(
                text("""
                    INSERT INTO sancionados (boe_document_id, nombre, identificador, expediente)
                    VALUES (:document_id, 'Persona legado', 'A123', 'EXP-1')
                """),
                {"document_id": document_id},
            )

    migrate.main()
    with sync_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        rows = connection.execute(
            text("SELECT codigo, origen_clave, estado_oportunidad FROM sancionados ORDER BY id")
        ).mappings().all()
    assert revision == "0004_clientes_crm"
    assert [row["codigo"] for row in rows] == ["OP-2025-000001", "OP-2025-000002"]
    assert len({row["origen_clave"] for row in rows}) == 2
    assert {row["estado_oportunidad"] for row in rows} == {"nueva"}
