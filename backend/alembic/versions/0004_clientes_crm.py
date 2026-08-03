"""Clientes/CRM core: clientes, notas, actividad, acciones agendadas.

Revision ID: 0004_clientes_crm
Revises: 0003_enrichment_core
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_clientes_crm"
down_revision = "0003_enrichment_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo", sa.String(14), nullable=False),
        sa.Column("nombre_razon_social", sa.String(500), nullable=False),
        sa.Column("tipo_persona", sa.String(20)),
        sa.Column("cif_nif", sa.String(20)),
        sa.Column("dni_nie", sa.String(20)),
        sa.Column("matriculas", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("persona_contacto", sa.String(200)),
        sa.Column("telefono", sa.String(50)),
        sa.Column("email", sa.String(200)),
        sa.Column("direccion_fiscal", sa.Text()),
        sa.Column("localidad", sa.String(200)),
        sa.Column("provincia", sa.String(200)),
        sa.Column("codigo_postal", sa.String(10)),
        sa.Column("web", sa.String(500)),
        sa.Column("sector", sa.String(200)),
        sa.Column("estado_cliente", sa.String(20), nullable=False, server_default="activo"),
        sa.Column("fecha_contrato", sa.Date()),
        sa.Column("precio_contrato", sa.Numeric(12, 2)),
        sa.Column("sancion_origen_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("codigo"),
        # Unique, not just indexed: this is what makes conversion idempotent —
        # a second POST /convertir on the same Sancionado cannot create a
        # second Cliente, database-enforced even under concurrent requests.
        sa.UniqueConstraint("sancion_origen_id"),
        sa.ForeignKeyConstraint(["sancion_origen_id"], ["sancionados.id"]),
        sa.CheckConstraint("estado_cliente IN ('activo', 'inactivo')", name="ck_clientes_estado_cliente"),
    )
    op.create_index("ix_clientes_cif_nif", "clientes", ["cif_nif"])
    op.create_index("ix_clientes_dni_nie", "clientes", ["dni_nie"])

    # Now that clientes exists, wire up the FK added as a bare column in 0003.
    with op.batch_alter_table("sancionados") as batch:
        batch.create_foreign_key("fk_sancionados_cliente_id", "clientes", ["cliente_id"], ["id"])

    op.create_table(
        "codigo_cliente_contadores",
        sa.Column("anio", sa.Integer(), primary_key=True),
        sa.Column("ultimo_valor", sa.Integer(), nullable=False),
    )

    op.create_table(
        "notas_cliente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("autor", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
    )
    op.create_index("ix_notas_cliente_cliente_id", "notas_cliente", ["cliente_id"])

    op.create_table(
        "actividades_cliente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("titulo", sa.String(500), nullable=False),
        sa.Column("detalle", sa.Text()),
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.CheckConstraint(
            "tipo IN ('llamada', 'email', 'pago', 'nota', 'conversion', 'sistema')",
            name="ck_actividades_cliente_tipo",
        ),
    )
    op.create_index("ix_actividades_cliente_cliente_id", "actividades_cliente", ["cliente_id"])

    op.create_table(
        "acciones_agendadas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("titulo", sa.String(500), nullable=False),
        sa.Column("fecha_programada", sa.DateTime(timezone=True)),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("notas", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.CheckConstraint("tipo IN ('llamada', 'email', 'tarea')", name="ck_acciones_agendadas_tipo"),
        sa.CheckConstraint("estado IN ('pendiente', 'hecha', 'cancelada')", name="ck_acciones_agendadas_estado"),
    )
    op.create_index("ix_acciones_agendadas_cliente_id", "acciones_agendadas", ["cliente_id"])


def downgrade() -> None:
    op.drop_index("ix_acciones_agendadas_cliente_id", table_name="acciones_agendadas")
    op.drop_table("acciones_agendadas")
    op.drop_index("ix_actividades_cliente_cliente_id", table_name="actividades_cliente")
    op.drop_table("actividades_cliente")
    op.drop_index("ix_notas_cliente_cliente_id", table_name="notas_cliente")
    op.drop_table("notas_cliente")
    op.drop_table("codigo_cliente_contadores")
    with op.batch_alter_table("sancionados") as batch:
        batch.drop_constraint("fk_sancionados_cliente_id", type_="foreignkey")
    op.drop_index("ix_clientes_dni_nie", table_name="clientes")
    op.drop_index("ix_clientes_cif_nif", table_name="clientes")
    op.drop_table("clientes")
