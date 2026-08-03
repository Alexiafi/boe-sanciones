"""Contact enrichment core: provenance fields, attempts log and cache.

Revision ID: 0003_enrichment_core
Revises: 0002_opportunity_core
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_enrichment_core"
down_revision = "0002_opportunity_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sancionados", sa.Column("web", sa.String(500)))
    op.add_column("sancionados", sa.Column("linkedin_url", sa.String(500)))
    op.add_column("sancionados", sa.Column("telefono_secundario", sa.String(50)))
    op.add_column(
        "sancionados",
        sa.Column("contacto_estado", sa.String(20), nullable=False, server_default="pendiente"),
    )
    op.add_column("sancionados", sa.Column("contacto_fuente", sa.String(50)))
    op.add_column("sancionados", sa.Column("contacto_url", sa.String(500)))
    op.add_column("sancionados", sa.Column("contacto_confidence", sa.Numeric(3, 2)))
    op.add_column("sancionados", sa.Column("contacto_actualizado_at", sa.DateTime(timezone=True)))
    # No FK yet: ``clientes`` is created in 0004_clientes_crm, which also adds
    # the foreign key constraint on this column.
    op.add_column("sancionados", sa.Column("cliente_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("sancionados") as batch:
        batch.create_check_constraint(
            "ck_sancionados_contacto_estado",
            "contacto_estado IN ('pendiente', 'encontrado', 'no_encontrado', 'manual')",
        )

    op.create_table(
        "enriquecimiento_intentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sancionado_id", sa.Integer(), nullable=False),
        sa.Column("proveedor", sa.String(50), nullable=False),
        sa.Column("consulta", sa.Text()),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column("url_origen", sa.String(500)),
        sa.Column("confidence", sa.Numeric(3, 2)),
        sa.Column("evidencia", sa.Text()),
        sa.Column("coste_estimado_eur", sa.Numeric(10, 4), server_default="0"),
        sa.Column("duracion_ms", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sancionado_id"], ["sancionados.id"]),
        sa.CheckConstraint(
            "resultado IN ('encontrado', 'no_encontrado', 'error', 'omitido')",
            name="ck_enriquecimiento_intentos_resultado",
        ),
    )
    op.create_index("ix_enriquecimiento_intentos_sancionado_id", "enriquecimiento_intentos", ["sancionado_id"])

    op.create_table(
        "enriquecimiento_cache",
        sa.Column("clave", sa.String(64), primary_key=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("enriquecimiento_cache")
    op.drop_index("ix_enriquecimiento_intentos_sancionado_id", table_name="enriquecimiento_intentos")
    op.drop_table("enriquecimiento_intentos")
    with op.batch_alter_table("sancionados") as batch:
        batch.drop_constraint("ck_sancionados_contacto_estado", type_="check")
        batch.drop_column("cliente_id")
        batch.drop_column("contacto_actualizado_at")
        batch.drop_column("contacto_confidence")
        batch.drop_column("contacto_url")
        batch.drop_column("contacto_fuente")
        batch.drop_column("contacto_estado")
        batch.drop_column("telefono_secundario")
        batch.drop_column("linkedin_url")
        batch.drop_column("web")
