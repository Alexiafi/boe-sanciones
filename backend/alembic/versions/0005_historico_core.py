"""Historical index core: historico_docs (FTS + JSONB GIN), historico_resultados,
historico_backfill_runs, and scraping_runs.tipo.

Revision ID: 0005_historico_core
Revises: 0004_clientes_crm
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_historico_core"
down_revision = "0004_clientes_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historico_docs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("boe_id", sa.String(50), nullable=False),
        sa.Column("fuente", sa.String(20), nullable=False),
        sa.Column("fecha_publicacion", sa.Date(), nullable=False),
        sa.Column("seccion_codigo", sa.String(10)),
        sa.Column("departamento_nombre", sa.String(500)),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("url_html", sa.Text()),
        sa.Column("url_xml", sa.Text()),
        sa.Column("url_pdf", sa.Text()),
        sa.Column("texto_plano", sa.Text()),
        sa.Column("extracto", sa.Text()),
        sa.Column("hash_texto", sa.String(64)),
        sa.Column("identificadores", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("matriculas", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("nombres", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column(
            "digitos_parciales", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column("nombres_norm", sa.Text(), nullable=False, server_default=""),
        sa.Column("familia_sancionadora", sa.String(50)),
        sa.Column("confidence", sa.Numeric(3, 2)),
        sa.Column("origen_indexado", sa.String(20), nullable=False, server_default="backfill"),
        sa.Column("indexer_version", sa.String(20), nullable=False, server_default="regex-1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("boe_id", name="uq_historico_docs_boe_id"),
        sa.CheckConstraint("fuente IN ('boe', 'teu')", name="ck_historico_docs_fuente"),
        sa.CheckConstraint(
            "origen_indexado IN ('backfill', 'diario', 'teu_publico')",
            name="ck_historico_docs_origen",
        ),
    )

    # Generated column, not a trigger and not application-maintained: PostgreSQL
    # guarantees tsv can never drift from nombres_norm. to_tsvector(regconfig,
    # text) with a literal config is IMMUTABLE (the 1-arg form is only STABLE),
    # which is what makes it legal here. 'simple' (not 'spanish') is used
    # because the indexed text is proper nouns: the Spanish stemmer/stopword
    # list would mangle surnames. Accents are stripped in Python before insert
    # (services/historico/patterns.normalizar_nombre), so this needs no
    # `CREATE EXTENSION unaccent` — which is STABLE (illegal in a generated
    # column) and can require superuser privileges to install.
    op.execute(
        "ALTER TABLE historico_docs ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(nombres_norm, ''))) STORED"
    )

    op.create_index(
        "ix_historico_docs_fecha_publicacion", "historico_docs", ["fecha_publicacion"]
    )
    op.execute("CREATE INDEX ix_historico_docs_tsv ON historico_docs USING gin (tsv)")
    op.execute(
        "CREATE INDEX ix_historico_docs_identificadores ON historico_docs "
        "USING gin (identificadores jsonb_path_ops)"
    )
    op.execute(
        "CREATE INDEX ix_historico_docs_matriculas ON historico_docs "
        "USING gin (matriculas jsonb_path_ops)"
    )

    op.create_table(
        "historico_resultados",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("historico_doc_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("via_match", sa.String(24), nullable=False),
        sa.Column("detalle_match", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="nuevo"),
        sa.Column("extraido", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("datos_extraidos", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("extraido_at", sa.DateTime(timezone=True)),
        sa.Column("extractor_version", sa.String(200)),
        sa.Column("extraccion_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["historico_doc_id"], ["historico_docs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("cliente_id", "historico_doc_id", name="uq_historico_resultados_cliente_doc"),
        sa.CheckConstraint(
            "via_match IN ('cif', 'dni', 'matricula', 'nombre', 'nombre_dni_parcial', 'teu_publico')",
            name="ck_historico_resultados_via_match",
        ),
        sa.CheckConstraint(
            "estado IN ('nuevo', 'confirmado', 'descartado')",
            name="ck_historico_resultados_estado",
        ),
    )
    op.create_index("ix_historico_resultados_cliente_id", "historico_resultados", ["cliente_id"])

    op.create_table(
        "historico_backfill_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=False),
        sa.Column("cursor_fecha", sa.Date()),
        sa.Column("ultima_fecha_completada", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("dias_totales", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dias_procesados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("docs_vistos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("docs_candidatos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("docs_indexados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errores", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log", sa.Text()),
        sa.Column("confirmacion_token", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("fecha_desde", "fecha_hasta", name="uq_historico_backfill_runs_rango"),
        sa.CheckConstraint(
            "status IN ('pendiente', 'en_curso', 'pausado', 'completado', 'error')",
            name="ck_historico_backfill_runs_status",
        ),
        sa.CheckConstraint("fecha_desde <= fecha_hasta", name="ck_historico_backfill_runs_rango_valido"),
    )

    # tipo distinguishes the daily/manual BOE pipeline from on-demand
    # historical-extraction audit rows (tasks/historico_extraccion.py). Both
    # run_scraping()'s "already completed" check and GET /api/scraping/gaps
    # must filter on tipo='diario' so a same-day extraction run never makes
    # either treat that date as covered.
    with op.batch_alter_table("scraping_runs") as batch:
        batch.add_column(sa.Column("tipo", sa.String(20), nullable=False, server_default="diario"))
        batch.create_check_constraint(
            "ck_scraping_runs_tipo", "tipo IN ('diario', 'historico_cliente')"
        )
    op.create_index("ix_scraping_runs_tipo_fecha", "scraping_runs", ["tipo", "fecha_boe"])


def downgrade() -> None:
    op.drop_index("ix_scraping_runs_tipo_fecha", table_name="scraping_runs")
    with op.batch_alter_table("scraping_runs") as batch:
        batch.drop_constraint("ck_scraping_runs_tipo", type_="check")
        batch.drop_column("tipo")

    op.drop_table("historico_backfill_runs")

    op.drop_index("ix_historico_resultados_cliente_id", table_name="historico_resultados")
    op.drop_table("historico_resultados")

    op.execute("DROP INDEX IF EXISTS ix_historico_docs_matriculas")
    op.execute("DROP INDEX IF EXISTS ix_historico_docs_identificadores")
    op.execute("DROP INDEX IF EXISTS ix_historico_docs_tsv")
    op.drop_index("ix_historico_docs_fecha_publicacion", table_name="historico_docs")
    op.drop_table("historico_docs")
