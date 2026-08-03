"""Opportunity core, extraction traceability and annual codes.

Revision ID: 0002_opportunity_core
Revises: 0001_legacy_baseline
Create Date: 2026-08-03
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "0002_opportunity_core"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None


def _normalise(value: object | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def _legacy_key(row: dict[str, object]) -> str:
    payload = "\x1f".join(
        _normalise(row.get(field))
        for field in ("boe_id", "identificador", "nombre", "expediente", "matricula_coche")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column("boe_documentos", sa.Column("extraction_status", sa.String(20), nullable=False, server_default="pending"))
    op.add_column("boe_documentos", sa.Column("extraction_attempted_at", sa.DateTime(timezone=True)))
    op.add_column("boe_documentos", sa.Column("extraction_error", sa.Text()))
    op.add_column("boe_documentos", sa.Column("extractor_version", sa.String(200)))

    op.add_column("sancionados", sa.Column("codigo", sa.String(14), nullable=True))
    op.add_column("sancionados", sa.Column("estado_oportunidad", sa.String(20), nullable=False, server_default="nueva"))
    op.add_column("sancionados", sa.Column("origen_clave", sa.String(64), nullable=True))
    op.add_column("sancionados", sa.Column("localidad", sa.String(200)))
    op.add_column("sancionados", sa.Column("provincia", sa.String(200)))
    op.add_column("sancionados", sa.Column("codigo_postal", sa.String(10)))
    op.add_column("sancionados", sa.Column("tipo_procedimiento", sa.String(30)))
    op.add_column("sancionados", sa.Column("importe_deuda_eur", sa.Numeric(12, 2)))
    op.add_column("sancionados", sa.Column("plazo_pago_voluntario", sa.String(200)))
    op.add_column("sancionados", sa.Column("fecha_resolucion", sa.Date()))
    op.add_column("sancionados", sa.Column("observaciones", sa.Text()))

    op.create_table(
        "codigo_oportunidad_contadores",
        sa.Column("anio", sa.Integer(), primary_key=True),
        sa.Column("ultimo_valor", sa.Integer(), nullable=False),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text("""
        SELECT s.id, d.boe_id, d.fecha_publicacion, s.identificador, s.nombre,
               s.expediente, s.matricula_coche
        FROM sancionados s
        JOIN boe_documentos d ON d.id = s.boe_document_id
        ORDER BY d.fecha_publicacion, s.id
    """)).mappings().all()
    counters: dict[int, int] = defaultdict(int)
    duplicate_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        year = row["fecha_publicacion"].year
        counters[year] += 1
        base_key = _legacy_key(dict(row))
        duplicate_counts[base_key] += 1
        key = base_key if duplicate_counts[base_key] == 1 else f"{base_key[:-8]}{row['id']:08x}"
        bind.execute(
            sa.text("UPDATE sancionados SET codigo=:codigo, origen_clave=:key, estado_oportunidad='nueva' WHERE id=:id"),
            {"codigo": f"OP-{year}-{counters[year]:06d}", "key": key, "id": row["id"]},
        )
    for year, last_value in counters.items():
        bind.execute(
            sa.text("INSERT INTO codigo_oportunidad_contadores (anio, ultimo_valor) VALUES (:year, :value)"),
            {"year": year, "value": last_value},
        )

    bind.execute(sa.text("""
        UPDATE boe_documentos d
        SET extraction_status = CASE
          WHEN EXISTS (SELECT 1 FROM sancionados s WHERE s.boe_document_id = d.id) THEN 'completed'
          ELSE 'pending'
        END
    """))

    with op.batch_alter_table("sancionados") as batch:
        batch.alter_column("codigo", nullable=False)
        batch.alter_column("origen_clave", nullable=False)
        batch.create_unique_constraint("uq_sancionados_codigo", ["codigo"])
        batch.create_unique_constraint("uq_sancionados_origen_clave", ["origen_clave"])
        batch.create_check_constraint(
            "ck_sancionados_estado_oportunidad",
            "estado_oportunidad IN ('nueva', 'revisada', 'contactada', 'descartada', 'cliente')",
        )
    with op.batch_alter_table("boe_documentos") as batch:
        batch.create_check_constraint(
            "ck_boe_documentos_extraction_status",
            "extraction_status IN ('pending', 'completed', 'error')",
        )

    op.add_column("scraping_runs", sa.Column("extraction_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("scraping_runs", sa.Column("extraction_provider", sa.String(50)))
    op.add_column("scraping_runs", sa.Column("extraction_limit", sa.Integer()))
    op.add_column("scraping_runs", sa.Column("extraction_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("scraping_runs") as batch:
        batch.drop_column("extraction_attempts")
        batch.drop_column("extraction_limit")
        batch.drop_column("extraction_provider")
        batch.drop_column("extraction_requested")
    with op.batch_alter_table("boe_documentos") as batch:
        batch.drop_constraint("ck_boe_documentos_extraction_status", type_="check")
        batch.drop_column("extractor_version")
        batch.drop_column("extraction_error")
        batch.drop_column("extraction_attempted_at")
        batch.drop_column("extraction_status")
    with op.batch_alter_table("sancionados") as batch:
        batch.drop_constraint("ck_sancionados_estado_oportunidad", type_="check")
        batch.drop_constraint("uq_sancionados_origen_clave", type_="unique")
        batch.drop_constraint("uq_sancionados_codigo", type_="unique")
        batch.drop_column("observaciones")
        batch.drop_column("fecha_resolucion")
        batch.drop_column("plazo_pago_voluntario")
        batch.drop_column("importe_deuda_eur")
        batch.drop_column("tipo_procedimiento")
        batch.drop_column("codigo_postal")
        batch.drop_column("provincia")
        batch.drop_column("localidad")
        batch.drop_column("origen_clave")
        batch.drop_column("estado_oportunidad")
        batch.drop_column("codigo")
    op.drop_table("codigo_oportunidad_contadores")
