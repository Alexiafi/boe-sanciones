"""Commercial documents core: plantillas_documento, documentos_comerciales,
contadores_factura, seeded with an explicitly provisional contract template.

Revision ID: 0006_documentos_comerciales
Revises: 0005_historico_core
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_documentos_comerciales"
down_revision = "0005_historico_core"
branch_labels = None
depends_on = None


# Deliberately not real contract/invoice copy: nobody should be able to send
# this to a client. services/documentos_comerciales.py refuses to treat a
# template containing this marker as ready without an explicit override, and
# the frontend always shows "PLANTILLA PROVISIONAL" on anything rendered from
# it. Judit must supply the final wording (see docs/GUIA_OPERATIVA.md).
PLANTILLA_CONTRATO_PROVISIONAL = """\
<div class="aviso-provisional">PLANTILLA PROVISIONAL — pendiente del texto contractual definitivo de la clienta. \
No enviar a ningún cliente real.</div>
<h1>Contrato de prestación de servicios</h1>
<p>Entre <strong>{{ emisor.nombre }}</strong> (CIF {{ emisor.cif }}), con domicilio en \
{{ emisor.direccion }}, y <strong>{{ cliente.nombre_razon_social }}</strong> \
(CIF/NIF {{ cliente.cif_nif }}), con domicilio en {{ cliente.direccion_fiscal }}.</p>
<p>Precio del servicio: <strong>{{ precio }} €</strong> (IVA {{ emisor.iva_porcentaje }}% no incluido).</p>
<p>Fecha: {{ fecha }}</p>
<p><em>[Aquí debe ir el texto contractual completo que aporte la clienta.]</em></p>
"""

PLANTILLA_FACTURA_PROVISIONAL = """\
<div class="aviso-provisional">PLANTILLA PROVISIONAL — revisar formato antes de emitir facturas reales.</div>
<h1>Factura {{ factura.numero }}</h1>
<p>Emisor: <strong>{{ emisor.nombre }}</strong> (CIF {{ emisor.cif }}) — {{ emisor.direccion }}</p>
<p>Cliente: <strong>{{ cliente.nombre_razon_social }}</strong> (CIF/NIF {{ cliente.cif_nif }}) — \
{{ cliente.direccion_fiscal }}</p>
<p>Fecha: {{ factura.fecha }}</p>
<table>
  <tr><th>Concepto</th><th>Importe</th></tr>
  <tr><td>{{ concepto }}</td><td>{{ cuantia }} €</td></tr>
</table>
<p>IVA ({{ emisor.iva_porcentaje }}%): {{ iva_importe }} €</p>
<p><strong>Total: {{ total }} €</strong></p>
"""


def upgrade() -> None:
    op.create_table(
        "plantillas_documento",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("contenido_html", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("tipo IN ('contrato', 'factura')", name="ck_plantillas_documento_tipo"),
    )
    op.create_index("ix_plantillas_documento_tipo_activo", "plantillas_documento", ["tipo", "activo"])

    op.create_table(
        "documentos_comerciales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("serie", sa.String(16)),
        sa.Column("numero", sa.String(32)),
        sa.Column("pdf_path", sa.Text()),
        sa.Column("datos", postgresql.JSONB(astext_type=sa.Text()), server_default="{}"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="generado"),
        sa.Column("email_destino", sa.String(200)),
        sa.Column("enviado_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("numero", name="uq_documentos_comerciales_numero"),
        sa.CheckConstraint("tipo IN ('contrato', 'factura')", name="ck_documentos_comerciales_tipo"),
        sa.CheckConstraint(
            "estado IN ('generado', 'enviado', 'error_envio')",
            name="ck_documentos_comerciales_estado",
        ),
    )
    op.create_index("ix_documentos_comerciales_cliente_id", "documentos_comerciales", ["cliente_id"])

    op.create_table(
        "contadores_factura",
        sa.Column("serie", sa.String(16), primary_key=True),
        sa.Column("anio", sa.Integer(), primary_key=True),
        sa.Column("ultimo_valor", sa.Integer(), nullable=False, server_default="0"),
    )

    plantillas = sa.table(
        "plantillas_documento",
        sa.column("tipo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("contenido_html", sa.Text),
        sa.column("version", sa.Integer),
        sa.column("activo", sa.Boolean),
    )
    op.bulk_insert(
        plantillas,
        [
            {
                "tipo": "contrato",
                "nombre": "Contrato estándar (provisional)",
                "contenido_html": PLANTILLA_CONTRATO_PROVISIONAL,
                "version": 1,
                "activo": True,
            },
            {
                "tipo": "factura",
                "nombre": "Factura estándar (provisional)",
                "contenido_html": PLANTILLA_FACTURA_PROVISIONAL,
                "version": 1,
                "activo": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("contadores_factura")
    op.drop_index("ix_documentos_comerciales_cliente_id", table_name="documentos_comerciales")
    op.drop_table("documentos_comerciales")
    op.drop_index("ix_plantillas_documento_tipo_activo", table_name="plantillas_documento")
    op.drop_table("plantillas_documento")
