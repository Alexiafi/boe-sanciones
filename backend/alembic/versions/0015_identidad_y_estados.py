"""Identity key on opportunities + a third client state.

- ``sancionados.identidad_clave``: the normalised, *complete* DNI/NIE/CIF of the
  party (NULL for masked or malformed identifiers). Two opportunities with the
  same key are the same person or company; that is what lets a new notification
  show the client it already is, inherit the contact data already found, and
  share edits between all its notifications. Masked identifiers
  (``***1234**``) must never share a key, hence NULL and not a partial value.
- ``clientes.estado_cliente`` admits ``informado``: converted prospects Judit
  only sends information to, kept apart from real (contracted) clients.

Revision ID: 0015_identidad_y_estados
Revises: 0014_pipeline_progreso
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_identidad_y_estados"
down_revision = "0014_pipeline_progreso"
branch_labels = None
depends_on = None

# Same shapes as services/identidad.FORMATO_ID_COMPLETO.
_FORMATO_ID = r"^([0-9]{8}[A-Z]|[XYZ][0-9]{7}[A-Z]|[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-J])$"


def upgrade() -> None:
    op.add_column("sancionados", sa.Column("identidad_clave", sa.String(20), nullable=True))
    op.create_index("ix_sancionados_identidad_clave", "sancionados", ["identidad_clave"])
    op.execute(
        sa.text(
            "UPDATE sancionados SET identidad_clave = t.clave FROM ("
            "  SELECT id, regexp_replace(upper(identificador), '[\\s.\\-]', '', 'g') AS clave "
            "  FROM sancionados WHERE identificador IS NOT NULL"
            ") t WHERE t.id = sancionados.id AND t.clave ~ :formato"
        ).bindparams(formato=_FORMATO_ID)
    )

    op.drop_constraint("ck_clientes_estado_cliente", "clientes", type_="check")
    op.create_check_constraint(
        "ck_clientes_estado_cliente", "clientes", "estado_cliente IN ('activo', 'informado', 'inactivo')"
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE clientes SET estado_cliente = 'activo' WHERE estado_cliente = 'informado'"))
    op.drop_constraint("ck_clientes_estado_cliente", "clientes", type_="check")
    op.create_check_constraint("ck_clientes_estado_cliente", "clientes", "estado_cliente IN ('activo', 'inactivo')")
    op.drop_index("ix_sancionados_identidad_clave", table_name="sancionados")
    op.drop_column("sancionados", "identidad_clave")
