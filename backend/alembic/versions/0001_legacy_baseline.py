"""Legacy schema baseline.

Revision ID: 0001_legacy_baseline
Revises:
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_legacy_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "boe_documentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("boe_id", sa.String(length=50), nullable=False),
        sa.Column("fecha_publicacion", sa.Date(), nullable=False),
        sa.Column("diario_numero", sa.Integer()),
        sa.Column("seccion_codigo", sa.String(length=10)),
        sa.Column("seccion_nombre", sa.String(length=200)),
        sa.Column("departamento_codigo", sa.String(length=50)),
        sa.Column("departamento_nombre", sa.String(length=500)),
        sa.Column("epigrafe_nombre", sa.String(length=500)),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("texto_plano", sa.Text()),
        sa.Column("hash_texto", sa.String(length=64)),
        sa.Column("familia_sancionadora", sa.String(length=50)),
        sa.Column("confidence", sa.Float()),
        sa.Column("match_rules", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("url_html", sa.Text()),
        sa.Column("url_xml", sa.Text()),
        sa.Column("url_pdf", sa.Text()),
        sa.Column("raw_sumario_item", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("source", sa.String(length=50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("boe_id"),
    )
    op.create_index("ix_boe_documentos_boe_id", "boe_documentos", ["boe_id"])
    op.create_index("ix_boe_documentos_fecha_publicacion", "boe_documentos", ["fecha_publicacion"])

    op.create_table(
        "sancionados",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("boe_document_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=500)),
        sa.Column("tipo_persona", sa.String(length=20)),
        sa.Column("identificador", sa.String(length=50)),
        sa.Column("tipo_identificador", sa.String(length=20)),
        sa.Column("direccion", sa.Text()),
        sa.Column("telefono", sa.String(length=50)),
        sa.Column("email", sa.String(length=200)),
        sa.Column("matricula_coche", sa.String(length=20)),
        sa.Column("importe_multa_eur", sa.Numeric(12, 2)),
        sa.Column("tipo_infraccion", sa.String(length=50)),
        sa.Column("razon_sancion", sa.Text()),
        sa.Column("expediente", sa.String(length=200)),
        sa.Column("estado_publicacion", sa.String(length=50)),
        sa.Column("plazo_notificacion", sa.String(length=200)),
        sa.Column("plazo_alegaciones", sa.String(length=200)),
        sa.Column("plazo_recurso", sa.String(length=200)),
        sa.Column("base_legal", sa.Text()),
        sa.Column("organismo_emisor", sa.String(length=500)),
        sa.Column("dominio_material", sa.String(length=200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["boe_document_id"], ["boe_documentos.id"]),
    )
    op.create_index("ix_sancionados_boe_document_id", "sancionados", ["boe_document_id"])
    op.create_index("ix_sancionados_identificador", "sancionados", ["identificador"])
    op.create_index("ix_sancionados_nombre", "sancionados", ["nombre"])

    op.create_table(
        "seguimientos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sancionado_id", sa.Integer(), nullable=False),
        sa.Column("nota", sa.Text()),
        sa.Column("estado", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sancionado_id"], ["sancionados.id"]),
    )
    op.create_index("ix_seguimientos_sancionado_id", "seguimientos", ["sancionado_id"])

    op.create_table(
        "notificaciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tipo", sa.String(length=50), nullable=False),
        sa.Column("titulo", sa.String(length=500), nullable=False),
        sa.Column("mensaje", sa.Text()),
        sa.Column("leida", sa.Boolean(), nullable=False),
        sa.Column("sancionado_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sancionado_id"], ["sancionados.id"]),
    )

    op.create_table(
        "scraping_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fecha_boe", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_docs", sa.Integer()),
        sa.Column("candidates", sa.Integer()),
        sa.Column("extracted", sa.Integer()),
        sa.Column("errors", sa.Integer()),
        sa.Column("error_log", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scraping_runs")
    op.drop_table("notificaciones")
    op.drop_index("ix_seguimientos_sancionado_id", table_name="seguimientos")
    op.drop_table("seguimientos")
    op.drop_index("ix_sancionados_nombre", table_name="sancionados")
    op.drop_index("ix_sancionados_identificador", table_name="sancionados")
    op.drop_index("ix_sancionados_boe_document_id", table_name="sancionados")
    op.drop_table("sancionados")
    op.drop_index("ix_boe_documentos_fecha_publicacion", table_name="boe_documentos")
    op.drop_index("ix_boe_documentos_boe_id", table_name="boe_documentos")
    op.drop_table("boe_documentos")
