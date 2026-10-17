"""Replace provisional invoice with En Plazo branded template.

Revision ID: 0010_factura_en_plazo
Revises: 0009_documento_archivos
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_factura_en_plazo"
down_revision = "0009_documento_archivos"
branch_labels = None
depends_on = None


FACTURA_EN_PLAZO = r"""
<style>
  @page { size: A4; margin: 12mm 14mm; }
  .invoice { color: #072d58; font-family: "DejaVu Sans", sans-serif; font-size: 8.5pt; }
  .top { display: table; width: 100%; margin-bottom: 7mm; }
  .brand, .issuer { display: table-cell; vertical-align: middle; }
  .brand { width: 43%; }
  .issuer { border-left: 1.5px solid #168de2; padding-left: 7mm; }
  .brand img { display: block; width: 88mm; height: auto; }
  .issuer h2 { margin: 0 0 2mm; font-size: 17pt; letter-spacing: 2px; }
  .issuer p { margin: 0.8mm 0; }
  .columns { display: table; width: 100%; margin-bottom: 4mm; }
  .meta, .client { display: table-cell; vertical-align: top; }
  .meta { width: 42%; padding-right: 6mm; }
  .client { background: #eef6fc; padding: 4mm; border-radius: 3mm; }
  h1 { color: #07386d; font-size: 20pt; margin: 0 0 4mm; }
  .section-title { font-size: 10pt; font-weight: 700; margin-bottom: 3mm; }
  .row { display: table; width: 100%; margin: 1.7mm 0; }
  .label, .value { display: table-cell; vertical-align: bottom; }
  .label { width: 42%; font-weight: 600; }
  .value { border-bottom: 1px solid #9ab9d4; padding: 0 1.5mm 1mm; color: #172c40; }
  .items { width: 100%; border-collapse: collapse; margin: 0 0 5mm; }
  .items th { background: #064a83; color: white; padding: 3mm; text-align: center; font-size: 8pt; }
  .items th:first-child, .items td:first-child { text-align: left; }
  .items td { height: 15mm; border: 1px solid #7fa9ca; padding: 3mm; color: #172c40; }
  .bottom { display: table; width: 100%; }
  .notes, .totals { display: table-cell; vertical-align: top; }
  .notes { width: 53%; background: #f1f7fb; border: 1px solid #c5dceb; padding: 4mm; }
  .totals { padding-left: 7mm; }
  .amount-row { display: table; width: 100%; margin-bottom: 2mm; }
  .amount-label, .amount { display: table-cell; padding: 2.5mm; }
  .amount { width: 37%; border: 1px solid #b9d0e2; text-align: right; color: #172c40; }
  .grand .amount-label { background: #064a83; color: white; font-weight: 700; }
  .grand .amount { border: 4px solid #064a83; font-weight: 700; }
  .bank { margin-top: 7mm; border-top: 1px solid #7fa9ca; padding-top: 4mm; line-height: 1.6; }
  .footer { margin-top: 7mm; border-top: 1px solid #7fa9ca; padding-top: 2mm; font-size: 7pt; }
</style>
<div class="invoice">
  <div class="top">
    <div class="brand"><img src="{{ factura.logo_data_uri }}" alt="En Plazo"></div>
    <div class="issuer">
      <h2>{{ emisor.nombre }}</h2>
      <p>CONTROL Y GESTIÓN ADMINISTRATIVA</p>
      <p>{{ emisor.direccion }}</p>
      <p>CIF: {{ emisor.cif }}</p>
    </div>
  </div>
  <div class="columns">
    <div class="meta">
      <h1>FACTURA</h1>
      <div class="row"><span class="label">Nº FACTURA:</span><span class="value">{{ factura.numero }}</span></div>
      <div class="row"><span class="label">FECHA DE EMISIÓN:</span><span class="value">{{ factura.fecha }}</span></div>
      <div class="row"><span class="label">FECHA DE VENCIMIENTO:</span><span class="value">{{ factura.fecha_vencimiento }}</span></div>
    </div>
    <div class="client">
      <div class="section-title">DATOS DEL CLIENTE</div>
      <div class="row"><span class="label">NOMBRE / RAZÓN SOCIAL:</span><span class="value">{{ cliente.nombre_razon_social }}</span></div>
      <div class="row"><span class="label">CIF / NIF:</span><span class="value">{{ cliente.cif_nif }}</span></div>
      <div class="row"><span class="label">DIRECCIÓN:</span><span class="value">{{ cliente.direccion_fiscal }}</span></div>
      <div class="row"><span class="label">CP / POBLACIÓN:</span><span class="value">{{ cliente.codigo_postal or '' }} {{ cliente.localidad or '' }}</span></div>
      <div class="row"><span class="label">PROVINCIA:</span><span class="value">{{ cliente.provincia or '' }}</span></div>
    </div>
  </div>
  <table class="items">
    <thead><tr><th>CONCEPTO / DESCRIPCIÓN</th><th>CANTIDAD</th><th>PRECIO UNITARIO</th><th>IMPORTE</th></tr></thead>
    <tbody><tr><td>{{ concepto }}</td><td>1</td><td>{{ cuantia }} €</td><td>{{ cuantia }} €</td></tr></tbody>
  </table>
  <div class="bottom">
    <div class="notes"><div class="section-title">OBSERVACIONES</div>Gracias por confiar en En Plazo.</div>
    <div class="totals">
      <div class="amount-row"><span class="amount-label">BASE IMPONIBLE</span><span class="amount">{{ cuantia }} €</span></div>
      <div class="amount-row"><span class="amount-label">IVA ({{ emisor.iva_porcentaje }}%)</span><span class="amount">{{ iva_importe }} €</span></div>
      <div class="amount-row grand"><span class="amount-label">TOTAL FACTURA</span><span class="amount">{{ total }} €</span></div>
    </div>
  </div>
  <div class="bank"><strong>DATOS BANCARIOS</strong><br>IBAN: {{ emisor.iban }}<br>Titular: {{ emisor.nombre }}<br>Concepto: Nº de factura {{ factura.numero }}</div>
  <div class="footer"><strong>EN PLAZO</strong> &nbsp;|&nbsp; Control y gestión administrativa <span style="float:right">CIF: {{ emisor.cif }}</span></div>
</div>
"""


def upgrade() -> None:
    plantillas = sa.table(
        "plantillas_documento",
        sa.column("tipo", sa.String), sa.column("nombre", sa.String),
        sa.column("contenido_html", sa.Text), sa.column("version", sa.Integer),
        sa.column("activo", sa.Boolean),
    )
    op.execute(plantillas.update().where(plantillas.c.tipo == "factura").values(activo=False))
    op.bulk_insert(plantillas, [{
        "tipo": "factura", "nombre": "Factura En Plazo", "contenido_html": FACTURA_EN_PLAZO,
        "version": 2, "activo": True,
    }])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plantillas_documento WHERE tipo = 'factura' AND version = 2"))
    op.execute(sa.text("UPDATE plantillas_documento SET activo = true WHERE tipo = 'factura' AND version = 1"))
