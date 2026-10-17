from __future__ import annotations

import json
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
    assert (revisions / "0009_documento_archivos.py").exists()
    assert (revisions / "0010_factura_en_plazo.py").exists()
    assert (revisions / "0011_config_batch_vinculo.py").exists()
    assert (revisions / "0012_contrato_en_plazo.py").exists()
    assert (revisions / "0013_contrato_actualizado.py").exists()
    assert (revisions / "0014_pipeline_progreso.py").exists()
    assert (revisions / "0015_identidad_y_estados.py").exists()
    assert (revisions / "0016_limpia_contacto_organismo.py").exists()
    assert (revisions / "0017_contrato_octubre.py").exists()


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
def test_migrations_reach_archivo_head(clean_database):
    inspector = inspect(sync_engine)
    assert "documento_archivos" in set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("documento_archivos")}
    assert {"boe_id", "content_type", "contenido", "bytes"}.issubset(columns)


@pytest.mark.integration
def test_downgrade_from_historico_head_round_trips():
    config = _alembic_config()
    command.downgrade(config, "0004_clientes_crm")
    inspector = inspect(sync_engine)
    assert "historico_docs" not in set(inspector.get_table_names())
    command.upgrade(config, "head")
    inspector = inspect(sync_engine)
    assert "historico_docs" in set(inspector.get_table_names())


def _insertar_aviso(connection, documento_id: int, n: int, **valores) -> None:
    columnas = {
        "boe_document_id": documento_id, "codigo": f"OP-MIG-{n:06d}", "origen_clave": f"mig-{n}".ljust(64, "x"),
        "estado_oportunidad": "nueva", "contacto_estado": "pendiente",
    }
    columnas.update(valores)
    connection.execute(
        text(f"INSERT INTO sancionados ({', '.join(columnas)}) VALUES ({', '.join(':' + c for c in columnas)})"),
        {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in columnas.items()},
    )


@pytest.mark.integration
def test_identity_key_is_backfilled_for_existing_rows(clean_database):
    config = _alembic_config()
    command.downgrade(config, "0014_pipeline_progreso")
    with sync_engine.begin() as connection:
        documento_id = connection.execute(text(
            "INSERT INTO boe_documentos (boe_id, fecha_publicacion, titulo) VALUES ('BOE-MIG-1', '2026-01-01', 'D') RETURNING id"
        )).scalar_one()
        for n, identificador in enumerate(["12.345.678-z", "b 12345678", "***4567**", "A-1", "NO CONSTA", None], start=1):
            _insertar_aviso(connection, documento_id, n, identificador=identificador)
    command.upgrade(config, "head")
    with sync_engine.connect() as connection:
        claves = {
            fila[0]: fila[1] for fila in connection.execute(text("SELECT identificador, identidad_clave FROM sancionados"))
        }
    assert claves["12.345.678-z"] == "12345678Z" and claves["b 12345678"] == "B12345678"
    assert claves["***4567**"] is None and claves["A-1"] is None and claves["NO CONSTA"] is None


@pytest.mark.integration
def test_information_only_clients_state_is_accepted_and_rolls_back(clean_database):
    config = _alembic_config()
    with sync_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO clientes (codigo, nombre_razon_social, estado_cliente) VALUES ('CLI-MIG-1', 'Solo info', 'informado')"
        ))
    command.downgrade(config, "0014_pipeline_progreso")   # 'informado' is not valid before 0015: demoted to 'activo'
    with sync_engine.connect() as connection:
        assert connection.execute(text("SELECT estado_cliente FROM clientes WHERE codigo = 'CLI-MIG-1'")).scalar_one() == "activo"
    command.upgrade(config, "head")


@pytest.mark.integration
def test_contact_that_belongs_to_the_administration_is_removed_but_manual_data_is_not(clean_database):
    config = _alembic_config()
    command.downgrade(config, "0015_identidad_y_estados")
    with sync_engine.begin() as connection:
        documento_id = connection.execute(text(
            "INSERT INTO boe_documentos (boe_id, fecha_publicacion, titulo) VALUES ('BOE-MIG-2', '2026-01-01', 'D') RETURNING id"
        )).scalar_one()
        # 1. harvested from the notice text (what the old enrichment did), with a non-URL "source"
        _insertar_aviso(
            connection, documento_id, 1, identificador="11111111H", telefono="611222333", email="oficina@x.test",
            contacto_estado="encontrado", contacto_fuente="teu",
            contacto_detalle={"telefono": {"valor": "611222333", "fuente_url": "historico-local", "confidence": 0.9}},
        )
        # 2. typed by hand: never touched, even if it looks institutional
        _insertar_aviso(connection, documento_id, 2, identificador="22222222J", telefono="012", contacto_estado="manual")
        # 3. the extraction copied a public-body number / domain
        _insertar_aviso(connection, documento_id, 3, identificador="33333333P", telefono="060", email="atencion@gencat.cat")
        # 4. one phone repeated across three different parties: the notice's own line
        for n, ident in enumerate(["44444444A", "55555555K", "66666666Q"], start=4):
            _insertar_aviso(connection, documento_id, n, identificador=ident, telefono="699 888 777")
        # 5. found on a real website: kept
        _insertar_aviso(
            connection, documento_id, 7, identificador="77777777B", telefono="933444555", web="https://acme.test",
            contacto_estado="encontrado", contacto_fuente="acme.test", contacto_url="https://acme.test/contacto",
            contacto_detalle={"telefono": {"valor": "933444555", "fuente_url": "https://acme.test/contacto", "confidence": 0.9}},
        )
        # 6. found on the web and shared by only two parties: kept (not enough to call it the notice's line)
        for n, ident in enumerate(["88888888Y", "99999999R"], start=8):
            _insertar_aviso(
                connection, documento_id, n, identificador=ident, telefono="655 444 333", contacto_estado="encontrado",
                contacto_fuente="gestoria.test",
                contacto_detalle={"telefono": {"valor": "655 444 333", "fuente_url": "https://gestoria.test/", "confidence": 0.9}},
            )
        # 7. a phone on a never-enriched row: it came out of the notice itself (the office's own line)
        _insertar_aviso(connection, documento_id, 10, identificador="10101010Q", telefono="942 751 245", email="multas@arona.test")
        # 8. an enriched row whose phone was NOT recorded by the enrichment: not trusted either
        _insertar_aviso(
            connection, documento_id, 11, identificador="12121212X", telefono="911 000 111", contacto_estado="pendiente",
        )
    command.upgrade(config, "head")
    with sync_engine.connect() as connection:
        filas = {
            fila["identificador"]: fila for fila in connection.execute(text(
                "SELECT identificador, telefono, email, contacto_estado, contacto_fuente, contacto_detalle FROM sancionados"
            )).mappings()
        }
    assert filas["11111111H"]["telefono"] is None and filas["11111111H"]["email"] is None
    assert filas["11111111H"]["contacto_estado"] == "pendiente" and filas["11111111H"]["contacto_fuente"] is None
    assert filas["11111111H"]["contacto_detalle"] is None
    assert filas["22222222J"]["telefono"] == "012" and filas["22222222J"]["contacto_estado"] == "manual"
    assert filas["33333333P"]["telefono"] is None and filas["33333333P"]["email"] is None
    assert all(filas[i]["telefono"] is None for i in ("44444444A", "55555555K", "66666666Q"))
    assert filas["77777777B"]["telefono"] == "933444555" and filas["77777777B"]["contacto_estado"] == "encontrado"
    assert filas["88888888Y"]["telefono"] == "655 444 333" and filas["99999999R"]["telefono"] == "655 444 333"
    assert filas["10101010Q"]["telefono"] is None and filas["10101010Q"]["email"] is None
    assert filas["12121212X"]["telefono"] is None


@pytest.mark.integration
def test_the_october_contract_is_the_active_template(clean_database):
    with sync_engine.connect() as connection:
        activas = connection.execute(text(
            "SELECT version, contenido_html FROM plantillas_documento WHERE tipo = 'contrato' AND activo ORDER BY version"
        )).all()
    assert [fila[0] for fila in activas] == [4]
    assert "REVISIÓN DE EXPEDIENTES ANTERIOR AL CONTRATO" in activas[0][1] and "B93993376" in activas[0][1]


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
        assert revision == "0017_contrato_octubre"
    assert [row["codigo"] for row in rows] == ["OP-2025-000001", "OP-2025-000002"]
    assert len({row["origen_clave"] for row in rows}) == 2
    assert {row["estado_oportunidad"] for row in rows} == {"nueva"}
