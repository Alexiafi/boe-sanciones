"""Copia archivada del documento original (PDF/HTML/XML) tal y como se
descargó, para que siga disponible aunque la fuente (suplemento de
notificaciones del BOE, TEU) lo retire de su web.

Revision ID: 0009_documento_archivos
Revises: 0008_vinculos_y_alertas_cliente
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_documento_archivos"
down_revision = "0008_vinculos_y_alertas_cliente"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documento_archivos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("boe_id", sa.String(50), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("contenido", sa.LargeBinary(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("url_origen", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("boe_id", name="uq_documento_archivos_boe_id"),
    )


def downgrade() -> None:
    op.drop_table("documento_archivos")
