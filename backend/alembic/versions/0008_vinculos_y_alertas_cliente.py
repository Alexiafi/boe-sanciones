"""Vínculos entre clientes (administrador/conductor/filial…), asignación
automática de sanciones a clientes existentes, y alertas de clientes en
notificaciones.

Revision ID: 0008_vinculos_y_alertas_cliente
Revises: 0007_contacto_detallado
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_vinculos_y_alertas_cliente"
down_revision = "0007_contacto_detallado"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vinculos_cliente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("cliente_vinculado_id", sa.Integer(), nullable=True),
        sa.Column("rol", sa.String(100), nullable=False),
        sa.Column("nombre", sa.String(500)),
        sa.Column("tipo_persona", sa.String(20)),
        sa.Column("identificador", sa.String(50)),
        sa.Column("tipo_identificador", sa.String(20)),
        sa.Column("telefono", sa.String(50)),
        sa.Column("email", sa.String(200)),
        sa.Column("notas", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.ForeignKeyConstraint(["cliente_vinculado_id"], ["clientes.id"]),
        # NULLs are distinct in a PostgreSQL unique constraint, so this only
        # blocks duplicating the *same* identifier twice under one client —
        # any number of vínculos without an identificador stay allowed.
        sa.UniqueConstraint("cliente_id", "identificador", name="uq_vinculos_cliente_cliente_identificador"),
    )
    op.create_index("ix_vinculos_cliente_cliente_id", "vinculos_cliente", ["cliente_id"])
    op.create_index("ix_vinculos_cliente_identificador", "vinculos_cliente", ["identificador"])

    op.add_column("sancionados", sa.Column("vinculo_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_sancionados_vinculo_id", "sancionados", "vinculos_cliente", ["vinculo_id"], ["id"], ondelete="SET NULL"
    )

    op.add_column("notificaciones", sa.Column("cliente_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_notificaciones_cliente_id", "notificaciones", "clientes", ["cliente_id"], ["id"]
    )
    op.create_index("ix_notificaciones_cliente_id", "notificaciones", ["cliente_id"])

    op.add_column("historico_resultados", sa.Column("vinculo_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_historico_resultados_vinculo_id",
        "historico_resultados",
        "vinculos_cliente",
        ["vinculo_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    with op.batch_alter_table("historico_resultados") as batch:
        batch.drop_constraint("fk_historico_resultados_vinculo_id", type_="foreignkey")
        batch.drop_column("vinculo_id")

    op.drop_index("ix_notificaciones_cliente_id", table_name="notificaciones")
    with op.batch_alter_table("notificaciones") as batch:
        batch.drop_constraint("fk_notificaciones_cliente_id", type_="foreignkey")
        batch.drop_column("cliente_id")

    with op.batch_alter_table("sancionados") as batch:
        batch.drop_constraint("fk_sancionados_vinculo_id", type_="foreignkey")
        batch.drop_column("vinculo_id")

    op.drop_index("ix_vinculos_cliente_identificador", table_name="vinculos_cliente")
    op.drop_index("ix_vinculos_cliente_cliente_id", table_name="vinculos_cliente")
    op.drop_table("vinculos_cliente")
