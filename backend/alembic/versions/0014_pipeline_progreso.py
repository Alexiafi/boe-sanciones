"""Pipeline progress + heartbeat, and a retry counter per document.

- ``scraping_runs.heartbeat_at/fase/progreso_*``: a run now reports where it
  is (descargando, extrayendo…) and stamps a heartbeat on every document, so a
  live run that legitimately takes a while is never mistaken for one a dead
  worker left behind (the old rule flipped anything older than 3 hours).
- ``boe_documentos.extraction_intentos``: how many times extraction was tried
  for the document; a failing document is retried a few times across runs
  instead of exactly once.

Revision ID: 0014_pipeline_progreso
Revises: 0013_contrato_actualizado
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_pipeline_progreso"
down_revision = "0013_contrato_actualizado"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scraping_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scraping_runs", sa.Column("fase", sa.String(30), nullable=True))
    op.add_column("scraping_runs", sa.Column("progreso_actual", sa.Integer(), nullable=True))
    op.add_column("scraping_runs", sa.Column("progreso_total", sa.Integer(), nullable=True))
    # BOE items already examined (fetched and judged) on this date: a later,
    # incremental run of the same date fetches only what is still missing
    # instead of re-downloading hundreds of non-candidate documents.
    op.add_column("scraping_runs", sa.Column("ids_revisados", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # {identifier: number of failed downloads}: an item that keeps failing is
    # given up on instead of being retried (and a run recorded) every pass.
    op.add_column("scraping_runs", sa.Column("ids_fallidos", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "boe_documentos",
        sa.Column("extraction_intentos", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("boe_documentos", "extraction_intentos")
    op.drop_column("scraping_runs", "ids_fallidos")
    op.drop_column("scraping_runs", "ids_revisados")
    op.drop_column("scraping_runs", "progreso_total")
    op.drop_column("scraping_runs", "progreso_actual")
    op.drop_column("scraping_runs", "fase")
    op.drop_column("scraping_runs", "heartbeat_at")
