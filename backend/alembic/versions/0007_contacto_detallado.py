"""Per-field contact provenance, social profiles and the sin_datos outcome.

Revision ID: 0007_contacto_detallado
Revises: 0006_documentos_comerciales
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_contacto_detallado"
down_revision = "0006_documentos_comerciales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sancionados", sa.Column("facebook_url", sa.String(500)))
    op.add_column("sancionados", sa.Column("instagram_url", sa.String(500)))
    op.add_column("sancionados", sa.Column("twitter_url", sa.String(500)))
    op.add_column(
        "sancionados",
        sa.Column("contacto_detalle", postgresql.JSONB(astext_type=sa.Text())),
    )
    # "sin_datos": the name is only a fiscal identifier and there is no
    # location, so no web search was even attempted (distinct from
    # "no_encontrado", where a search ran and found nothing).
    with op.batch_alter_table("sancionados") as batch:
        batch.drop_constraint("ck_sancionados_contacto_estado", type_="check")
        batch.create_check_constraint(
            "ck_sancionados_contacto_estado",
            "contacto_estado IN ('pendiente', 'encontrado', 'no_encontrado', 'manual', 'sin_datos')",
        )
    with op.batch_alter_table("enriquecimiento_intentos") as batch:
        batch.drop_constraint("ck_enriquecimiento_intentos_resultado", type_="check")
        batch.create_check_constraint(
            "ck_enriquecimiento_intentos_resultado",
            "resultado IN ('encontrado', 'no_encontrado', 'error', 'omitido', 'sin_datos')",
        )


def downgrade() -> None:
    with op.batch_alter_table("enriquecimiento_intentos") as batch:
        batch.drop_constraint("ck_enriquecimiento_intentos_resultado", type_="check")
        batch.create_check_constraint(
            "ck_enriquecimiento_intentos_resultado",
            "resultado IN ('encontrado', 'no_encontrado', 'error', 'omitido')",
        )
    with op.batch_alter_table("sancionados") as batch:
        batch.drop_constraint("ck_sancionados_contacto_estado", type_="check")
        batch.create_check_constraint(
            "ck_sancionados_contacto_estado",
            "contacto_estado IN ('pendiente', 'encontrado', 'no_encontrado', 'manual')",
        )
        batch.drop_column("contacto_detalle")
        batch.drop_column("twitter_url")
        batch.drop_column("instagram_url")
        batch.drop_column("facebook_url")
