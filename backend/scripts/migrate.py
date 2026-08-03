"""Apply Alembic revisions and safely bootstrap a legacy local database."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


LEGACY_COLUMNS = {
    "boe_documentos": {"id", "boe_id", "fecha_publicacion", "titulo", "source", "created_at"},
    "sancionados": {"id", "boe_document_id", "nombre", "identificador", "expediente", "created_at"},
    "seguimientos": {"id", "sancionado_id", "estado", "created_at"},
    "notificaciones": {"id", "tipo", "titulo", "leida", "created_at"},
    "scraping_runs": {"id", "fecha_boe", "status", "created_at"},
}


def _alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.database_url_sync)
    return config


def _legacy_schema_is_valid(engine) -> bool:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not set(LEGACY_COLUMNS).issubset(tables):
        return False
    return all(
        required.issubset({column["name"] for column in inspector.get_columns(table)})
        for table, required in LEGACY_COLUMNS.items()
    )


def main() -> None:
    config = _alembic_config()
    engine = create_engine(settings.database_url_sync)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "alembic_version" not in tables:
        app_tables = tables.intersection(LEGACY_COLUMNS)
        if not app_tables:
            command.upgrade(config, "head")
            return
        if not _legacy_schema_is_valid(engine):
            raise RuntimeError(
                "La base existente no coincide con el esquema legado esperado; "
                "no se ha marcado Alembic. Revise o haga copia antes de migrar."
            )
        command.stamp(config, "0001_legacy_baseline")

    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
