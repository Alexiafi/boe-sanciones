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
    assert (revisions / "0005_historico_core.py").exists()
    assert (revisions / "0006_documentos_comerciales.py").exists()
    assert (revisions / "0007_contacto_detallado.py").exists()
    assert (revisions / "0008_vinculos_y_alertas_cliente.py").exists()


@pytest.mark.integration
def test_migrations_reach_historico_head(clean_database):
    inspector = inspect(sync_engine)
    tables = set(inspector.get_table_names())
    assert {
        "historico_docs", "historico_resultados", "historico_backfill_runs",
        "plantillas_documento", "documentos_comerciales", "contadores_factura",
    }.issubset(tables)

    scraping_columns = {column["name"] for column in inspector.get_columns("scraping_runs")}
    assert "tipo" in scraping_columns

    gin_indexes = {
        row[0]
        for row in sync_engine.connect().execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'historico_docs' "
                "AND indexdef ILIKE '%USING gin%'"
            )
        )
    }
    assert {
        "ix_historico_docs_tsv",
        "ix_historico_docs_identificadores",
        "ix_historico_docs_matriculas",
    }.issubset(gin_indexes)

    with sync_engine.begin() as connection:
        tsv = connection.execute(
            text(
                "INSERT INTO historico_docs "
                "(boe_id, fuente, fecha_publicacion, titulo, nombres_norm) "
                "VALUES ('BOE-TEST-TSV', 'boe', '2026-01-01', 'Prueba', 'ACME LOGISTICA SL') "
                "RETURNING tsv"
            )
        ).scalar_one()
        assert tsv is not None
        matched = connection.execute(
            text(
                "SELECT 1 FROM historico_docs WHERE boe_id = 'BOE-TEST-TSV' "
                "AND tsv @@ plainto_tsquery('simple', 'ACME LOGISTICA')"
            )
        ).scalar_one_or_none()
        assert matched == 1
        connection.execute(text("DELETE FROM historico_docs WHERE boe_id = 'BOE-TEST-TSV'"))


@pytest.mark.integration
def test_migrations_reach_vinculos_head(clean_database):
    inspector = inspect(sync_engine)
    tables = set(inspector.get_table_names())
    assert "vinculos_cliente" in tables

    sancionados_columns = {column["name"] for column in inspector.get_columns("sancionados")}
    assert "vinculo_id" in sancionados_columns
    notificaciones_columns = {column["name"] for column in inspector.get_columns("notificaciones")}
    assert "cliente_id" in notificaciones_columns
    historico_resultados_columns = {column["name"] for column in inspector.get_columns("historico_resultados")}
    assert "vinculo_id" in historico_resultados_columns


@pytest.mark.integration
def test_downgrade_from_historico_head_round_trips():
    config = _alembic_config()
    command.downgrade(config, "0004_clientes_crm")
    inspector = inspect(sync_engine)
    assert "historico_docs" not in set(inspector.get_table_names())
    command.upgrade(config, "head")
    inspector = inspect(sync_engine)
    assert "historico_docs" in set(inspector.get_table_names())


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
    assert revision == "0008_vinculos_y_alertas_cliente"
    assert [row["codigo"] for row in rows] == ["OP-2025-000001", "OP-2025-000002"]
    assert len({row["origen_clave"] for row in rows}) == 2
    assert {row["estado_oportunidad"] for row in rows} == {"nueva"}
