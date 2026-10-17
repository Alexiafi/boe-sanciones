"""Configuración editable en runtime, extracción por OpenAI Batch API y
conversión de un vínculo (administrador, filial…) en cliente propio.

- ``configuracion_app``: pares clave/valor JSONB que Judit cambia desde la
  UI (modo de extracción tiempo real/batch, extracción automática diaria,
  topes por ejecución). Ver ``services/configuracion.py``.
- ``extracciones_batch`` / ``extracciones_batch_items``: seguimiento de cada
  lote enviado a la Batch API de OpenAI y de cada documento incluido.
- ``clientes.sancion_origen_id`` pasa a ser NULLABLE: un cliente creado a
  partir de un vínculo (el administrador de una sociedad ya cliente) no
  nace de una oportunidad. La unicidad se mantiene (PostgreSQL permite
  varios NULL en un índice UNIQUE).
- ``clientes.vinculo_origen_id``: traza de qué vínculo dio lugar al cliente.
- ``boe_documentos.extraction_status`` admite ``batch_pending`` (documento
  en un lote de la Batch API cuyo resultado aún no ha llegado).

Revision ID: 0011_config_batch_vinculo
Revises: 0010_factura_en_plazo
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_config_batch_vinculo"
down_revision = "0010_factura_en_plazo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "configuracion_app",
        sa.Column("clave", sa.String(64), primary_key=True),
        sa.Column("valor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "extracciones_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("scraping_run_id", sa.Integer(), sa.ForeignKey("scraping_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("modelo", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="preparando"),
        sa.Column("openai_batch_id", sa.String(100), nullable=True),
        sa.Column("input_file_id", sa.String(100), nullable=True),
        sa.Column("output_file_id", sa.String(100), nullable=True),
        sa.Column("error_file_id", sa.String(100), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errores", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sancionados_creados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("enviado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("tipo IN ('diario', 'historico_cliente')", name="ck_extracciones_batch_tipo"),
        sa.CheckConstraint(
            "status IN ('preparando', 'enviado', 'en_progreso', 'completado', 'fallido', 'expirado', 'cancelado')",
            name="ck_extracciones_batch_status",
        ),
    )
    op.create_index("ix_extracciones_batch_status", "extracciones_batch", ["status"])
    op.create_index("ix_extracciones_batch_openai_batch_id", "extracciones_batch", ["openai_batch_id"])

    op.create_table(
        "extracciones_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("extracciones_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("custom_id", sa.String(64), nullable=False),
        sa.Column("boe_document_id", sa.Integer(), sa.ForeignKey("boe_documentos.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "historico_resultado_id", sa.BigInteger(),
            sa.ForeignKey("historico_resultados.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("afectados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("batch_id", "custom_id", name="uq_extracciones_batch_items_custom_id"),
        sa.CheckConstraint("status IN ('pendiente', 'completado', 'error')", name="ck_extracciones_batch_items_status"),
    )
    op.create_index("ix_extracciones_batch_items_batch_id", "extracciones_batch_items", ["batch_id"])
    op.create_index("ix_extracciones_batch_items_boe_document_id", "extracciones_batch_items", ["boe_document_id"])

    op.drop_constraint("ck_boe_documentos_extraction_status", "boe_documentos", type_="check")
    op.create_check_constraint(
        "ck_boe_documentos_extraction_status", "boe_documentos",
        "extraction_status IN ('pending', 'completed', 'error', 'batch_pending')",
    )

    op.alter_column("clientes", "sancion_origen_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "clientes",
        sa.Column(
            "vinculo_origen_id", sa.Integer(),
            sa.ForeignKey("vinculos_cliente.id", ondelete="SET NULL", name="fk_clientes_vinculo_origen_id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.execute("UPDATE boe_documentos SET extraction_status = 'pending' WHERE extraction_status = 'batch_pending'")
    op.drop_constraint("ck_boe_documentos_extraction_status", "boe_documentos", type_="check")
    op.create_check_constraint(
        "ck_boe_documentos_extraction_status", "boe_documentos",
        "extraction_status IN ('pending', 'completed', 'error')",
    )
    op.drop_column("clientes", "vinculo_origen_id")
    # Clients born from a vínculo have no originating sanction; they cannot
    # survive a NOT NULL constraint, so remove them before restoring it.
    op.execute("DELETE FROM clientes WHERE sancion_origen_id IS NULL")
    op.alter_column("clientes", "sancion_origen_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_extracciones_batch_items_boe_document_id", table_name="extracciones_batch_items")
    op.drop_index("ix_extracciones_batch_items_batch_id", table_name="extracciones_batch_items")
    op.drop_table("extracciones_batch_items")
    op.drop_index("ix_extracciones_batch_openai_batch_id", table_name="extracciones_batch")
    op.drop_index("ix_extracciones_batch_status", table_name="extracciones_batch")
    op.drop_table("extracciones_batch")
    op.drop_table("configuracion_app")
