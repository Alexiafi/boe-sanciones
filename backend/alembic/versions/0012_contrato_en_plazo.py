"""Replace provisional contract with the real En Plazo contract text supplied
by the clienta (CONTRATO DE PRESTACIÓN DE SERVICIOS DE CONTROL Y GESTIÓN
ADMINISTRATIVA). Same pattern as 0010_factura_en_plazo: deactivate the
seeded provisional template, insert the real one as the new active version.

Revision ID: 0012_contrato_en_plazo
Revises: 0011_config_batch_vinculo
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_contrato_en_plazo"
down_revision = "0011_config_batch_vinculo"
branch_labels = None
depends_on = None


CONTRATO_EN_PLAZO = r"""
<style>
  .contrato { color: #181c1e; font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; line-height: 1.5; }
  .contrato h1 { font-size: 14pt; margin: 0 0 1em; }
  .contrato h2 { font-size: 11pt; margin: 1.4em 0 0.5em; }
  .contrato .parte { margin: 0.9em 0; }
  .contrato .campo { margin: 0.3em 0; }
  .contrato .campo .label { font-weight: 600; }
  .contrato hr { border: none; border-top: 1px solid #c4c6cf; margin: 1.2em 0; }
  .contrato .firma-bloque { margin-top: 1em; }
  .contrato .firma-linea { margin-top: 1.8em; border-top: 1px solid #181c1e; width: 70%; }
</style>
<div class="contrato">
<h1>CONTRATO DE PRESTACIÓN DE SERVICIOS DE CONTROL Y GESTIÓN ADMINISTRATIVA</h1>

<p>En {{ contrato.lugar }}, a {{ contrato.fecha_larga }}.</p>

<h2>REUNIDOS</h2>
<p>De una parte, <strong>{{ emisor.nombre }}</strong>, con CIF <strong>{{ emisor.cif }}</strong>,
con domicilio en {{ emisor.direccion }}, en adelante, <strong>EN PLAZO</strong>.</p>

<p>Y de otra, D./D.ª / Empresa:</p>
<div class="parte">
  <div class="campo"><span class="label">Nombre / Razón social:</span> {{ cliente.nombre_razon_social }}</div>
  <div class="campo"><span class="label">DNI / NIF / CIF:</span> {{ cliente.cif_nif }}</div>
  <div class="campo"><span class="label">Domicilio:</span> {{ cliente.direccion_fiscal }}</div>
  <div class="campo"><span class="label">Teléfono:</span> {{ cliente.telefono or "" }}</div>
  <div class="campo"><span class="label">Email:</span> {{ cliente.email or "" }}</div>
</div>
<p>En adelante, <strong>EL CLIENTE</strong>.</p>

<p>Ambas partes se reconocen capacidad suficiente para contratar y acuerdan las siguientes:</p>

<h2>CONDICIONES</h2>
<h2>1. SERVICIO CONTRATADO</h2>
<div class="campo"><span class="label">Servicio contratado:</span> {{ servicio }}</div>
<div class="campo"><span class="label">Precio:</span> {{ precio }} € + IVA</div>
<div class="campo"><span class="label">Forma de pago:</span> {{ forma_pago }}</div>
<div class="campo"><span class="label">Fecha de inicio:</span> {{ contrato.fecha_inicio }}</div>
<div class="campo"><span class="label">Fecha de finalización:</span> {{ contrato.fecha_fin }}</div>
<div class="campo"><span class="label">Duración:</span> 12 meses.</div>

<p>El CLIENTE contrata exclusivamente el servicio indicado en este apartado, con el alcance y
condiciones establecidos en el presente contrato.</p>

<hr>
<h2>2. SERVICIOS Y TARIFAS</h2>

<h2 style="font-size:10pt;">ALERTA TRÁFICO – EMPRESAS</h2>
<p><strong>Precio: 125 € + IVA al año.</strong></p>
<p>Incluye el control y detección de multas y notificaciones de tráfico, así como su comunicación al
CLIENTE durante un año desde la fecha de pago del servicio.</p>
<p>Queda incluida una primera gestión, siempre que se contrate la anualidad.</p>
<p>Cuando el CLIENTE sea una empresa, las alertas de tráfico correspondientes a su administrador
estarán incluidas sin coste adicional dentro del servicio contratado por la empresa.</p>
<p>La gestión de posteriores multas o procedimientos personales del administrador no estará incluida
y podrá contratarse de forma independiente en las condiciones especiales aplicables a clientes de
EN PLAZO.</p>

<hr>
<h2 style="font-size:10pt;">ALERTA TRÁFICO – PERSONAS FÍSICAS</h2>
<p>— Nuevos clientes<br><strong>Precio: 98€ + IVA al año.</strong></p>
<p>Incluye control, detección y aviso de las notificaciones de tráfico, así como una primera gestión.</p>
<p>— Personas físicas vinculadas a clientes de EN PLAZO<br><strong>Precio: 75 € + IVA al año por persona añadida.</strong></p>
<p>Esta tarifa será aplicable a personas incorporadas al servicio por su vinculación con un cliente de
EN PLAZO, incluyendo administradores u otras personas que el cliente designe. Incluye igualmente
el servicio de alerta y una primera gestión.</p>

<hr>
<h2 style="font-size:10pt;">ALERTA Y GESTIÓN TRÁFICO – EMPRESAS</h2>
<p><strong>Precio: 230€ + IVA al año.</strong></p>
<p>Incluye el control, aviso y gestión de las multas y procedimientos de tráfico correspondientes a las
matrículas de la empresa incluidas en el servicio, siempre que sean multas con fecha posterior a la
contratación del servicio.</p>
<p>También incluye las alertas de tráfico correspondientes al administrador.</p>
<p>La gestión comprende hasta 15 gestiones al año. Podrá incluir, según las características del
expediente: identificación de conductores, alegaciones, recursos, presentación de escritos,
contestación a requerimientos, aportación de documentación, consulta de expedientes y
seguimiento del procedimiento.</p>
<p>Una vez alcanzadas las 15 multas gestionadas, podrán contratarse 10 gestiones adicionales por
89 + IVA.</p>

<hr>
<h2 style="font-size:10pt;">ALERTA Y GESTIÓN TRÁFICO – PERSONAS FÍSICAS</h2>
<p>— Nuevos clientes<br><strong>Precio: 140€ + IVA al año.</strong></p>
<p>Incluye control, aviso y gestión de las multas y procedimientos de tráfico, hasta un máximo de 15
multas gestionadas al año.</p>
<p>— Personas físicas que ya sean clientes de EN PLAZO<br><strong>Precio: 95 € + IVA al año.</strong></p>
<p>Se aplican las mismas condiciones y el límite de 15 multas gestionadas al año. Una vez alcanzado
dicho límite, podrán contratarse 10 gestiones adicionales por 79€ + IVA.</p>

<hr>
<h2 style="font-size:10pt;">ALERTA 360</h2>
<p><strong>90€ + IVA al año.</strong></p>
<p>ALERTA 360 es un servicio que puede contratarse por sí mismo o añadirse a un servicio ya
contratado. Amplía el control y aviso a comunicaciones administrativas procedentes de diferentes
organismos y materias, además de tráfico. Puede comprender, entre otras: impuestos, tasas,
requerimientos, comparecencias, deudas, embargos, procedimientos administrativos y otras
comunicaciones oficiales.</p>
<p>ALERTA 360 comprende el control y aviso. Se envía la notificación con el organismo y número de
expediente para que el cliente pueda atenderla en plazo. La gestión de estas actuaciones no queda
incluida, salvo comparecencias expedidas por la diputación de Barcelona, las cuales se puede
averiguar en nombre del cliente las razones de comparecencia.</p>
<p>Cuando una actuación requiera autorización, certificado digital o representación electrónica, el
CLIENTE deberá facilitar los medios necesarios en caso de estar de acuerdo.</p>

<hr>
<h2 style="font-size:10pt;">GESTIÓN INTEGRAL</h2>
<p><strong>226 € + IVA al año.</strong></p>
<p>La GESTIÓN INTEGRAL permite al CLIENTE externalizar con EN PLAZO el control y gestión de sus
notificaciones y actuaciones administrativas dentro del ámbito contratado. Para contratar este
servicio será necesario disponer previamente de un servicio de alerta contratado con EN PLAZO.
La prestación podrá requerir certificado digital, apoderamiento o representación electrónica
válida. Incluye hasta 30 gestiones administrativas al año. Una vez alcanzado el límite, podrán
contratarse los bonos de los servicios de alerta y gestión.</p>

<h2>NOTIFICACIONES Y EXPEDIENTES ANTERIORES AL CONTRATO</h2>
<p>Quedan fuera de los servicios ordinarios contratados las multas, sanciones, notificaciones, deudas y
procedimientos emitidos o iniciados con anterioridad a la fecha de inicio del presente contrato,
aunque sean detectados durante su vigencia.</p>
<p>Estos expedientes podrán ser objeto de revisión y gestión mediante el servicio de REVISIÓN DE
DEUDA o mediante el presupuesto correspondiente. Esta condición se aplicará tanto si el
expediente se encuentra dentro de plazo como si se encuentra en una fase posterior.</p>

<h2 style="font-size:10pt;">REVISIÓN DE DEUDA</h2>
<p>La revisión inicial de deuda será gratuita. EN PLAZO realizará una comprobación inicial para
determinar la existencia de expedientes o deudas susceptibles de gestión. Una vez realizada la
revisión, se emitirá al CLIENTE un informe y las posibilidades de actuación.</p>
<p>La gestión posterior se cobrará por expediente: <strong>clientes de EN PLAZO, 25 € + IVA por
expediente; no clientes, 40 € + IVA por expediente.</strong></p>
<p>La gestión podrá comprender, cuando proceda, la preparación y presentación de escritos, recursos
y solicitudes, así como la comunicación y seguimiento del expediente ante la Administración.</p>
<p>Cuando la deuda se encuentre dentro de plazo y legalmente sea posible actuar, EN PLAZO realizará
las actuaciones dirigidas a intentar evitar o detener la continuación del procedimiento
administrativo y, cuando proceda, su paso a vía ejecutiva y las consecuencias derivadas de la
misma. El resultado dependerá siempre de la Administración competente.</p>

<hr>
<h2>4. PRESTACIÓN DEL SERVICIO</h2>
<p>EN PLAZO realizará las actuaciones correspondientes al servicio contratado utilizando los medios y
sistemas que considere adecuados para su prestación. Las notificaciones detectadas para los
servicios de alerta serán comunicadas al CLIENTE dentro del plazo de actuación.</p>
<p>El CLIENTE deberá facilitar la información, documentación, instrucciones y autorizaciones
necesarias para realizar las actuaciones contratadas. Cuando una actuación requiera respuesta o
documentación del CLIENTE y esta no sea facilitada a tiempo, EN PLAZO no podrá garantizar su
realización dentro del plazo administrativo correspondiente.</p>

<h2>5. REPRESENTACIÓN Y AUTORIZACIONES</h2>
<p>Determinadas actuaciones ante las Administraciones Públicas requieren identificación, autorización
o representación del interesado. Cuando sea necesario, el CLIENTE facilitará el correspondiente
apoderamiento, autorización, certificado digital o sistema de representación electrónica válido.</p>
<p>EN PLAZO no solicitará al CLIENTE sus contraseñas personales ni utilizará mecanismos de acceso
que no estén autorizados. La contratación del servicio no sustituye las autorizaciones que pueda
exigir una Administración para una actuación concreta.</p>

<h2>6. COMUNICACIONES Y PLAZOS</h2>
<p>Las comunicaciones entre EN PLAZO y el CLIENTE podrán realizarse mediante correo electrónico,
WhatsApp, teléfono u otros medios acordados. Los avisos realizados por EN PLAZO tienen carácter
complementario y no sustituyen las notificaciones oficiales realizadas por las Administraciones
Públicas. El CLIENTE deberá mantener actualizados sus datos de contacto y atender las
comunicaciones de EN PLAZO cuando resulte necesaria su intervención.</p>

<h2>7. RESULTADO DE LAS ACTUACIONES</h2>
<p>EN PLAZO realizará las actuaciones contratadas con la diligencia profesional correspondiente. La
resolución de los procedimientos corresponde al organismo o Administración competente. Por
ello, EN PLAZO no garantiza la aceptación de recursos, alegaciones, solicitudes, identificaciones,
aplazamientos, paralizaciones u otras actuaciones presentadas ante una Administración.</p>

<h2>8. ORIENTACIÓN ADMINISTRATIVA Y PROFESIONALES COLABORADORES</h2>
<p>EN PLAZO prestará orientación administrativa relacionada con los asuntos incluidos en el servicio
contratado. Cuando la naturaleza de un asunto requiera asesoramiento jurídico especializado o
intervención profesional propia de la abogacía, EN PLAZO podrá coordinar la intervención de
abogados y otros profesionales colaboradores con los que mantenga acuerdos de colaboración. La
intervención profesional y, en su caso, sus honorarios se comunicarán al CLIENTE antes de su
contratación cuando no estén incluidos en el servicio contratado con EN PLAZO. El CLIENTE podrá
mantener igualmente su propia gestoría, asesoría o despacho de abogados, pudiendo EN PLAZO
coordinarse con ellos cuando así lo solicite.</p>

<h2>9. PROTECCIÓN DE DATOS Y CONFIDENCIALIDAD</h2>
<p>EN PLAZO tratará los datos personales necesarios para prestar los servicios contratados de
conformidad con el Reglamento General de Protección de Datos, la normativa española aplicable y
demás legislación vigente. La condición de EN PLAZO como responsable o encargado del
tratamiento se determinará atendiendo a la naturaleza y finalidad de cada tratamiento. Cuando EN
PLAZO actúe como encargado del tratamiento por cuenta del CLIENTE, se formalizará, cuando
corresponda, el correspondiente acuerdo de encargo de tratamiento.</p>
<p>EN PLAZO podrá tratar, entre otros, datos identificativos, datos de contacto, datos relativos a
vehículos, multas, sanciones, expedientes y procedimientos administrativos necesarios para la
prestación del servicio. La información y documentación del CLIENTE será tratada de forma
confidencial y se aplicarán las medidas de seguridad exigibles conforme a la normativa vigente.</p>

<h2>10. PRECIO Y FORMA DE PAGO</h2>
<p>El precio aplicable será el indicado en el apartado SERVICIO CONTRATADO. El pago podrá
realizarse mediante transferencia bancaria, tarjeta a través de TPV u otro medio acordado entre las
partes. Los pagos realizados mediante TPV corresponderán exclusivamente al importe previamente
aceptado por el CLIENTE. No se realizarán cargos adicionales o recurrentes en la tarjeta sin
autorización expresa del CLIENTE. Las ampliaciones de servicio, bloques adicionales o actuaciones
no incluidas serán comunicadas al CLIENTE antes de su contratación.</p>

<h2>11. DURACIÓN Y RENOVACIÓN</h2>
<p>El contrato tendrá una duración de 12 meses desde la fecha de inicio indicada. Podrá renovarse por
periodos sucesivos de 12 meses. Cualquiera de las partes podrá comunicar su voluntad de no
renovar el contrato con una antelación mínima de un mes respecto de la fecha de vencimiento.</p>

<h2>12. FINALIZACIÓN DEL SERVICIO</h2>
<p>Finalizado el contrato, EN PLAZO dejará de iniciar nuevas actuaciones no incluidas en el periodo
contratado. Los asuntos que se encuentren en curso podrán ser coordinados con el CLIENTE o con
los profesionales que este designe, teniendo en cuenta el estado del procedimiento y las
obligaciones legales aplicables. La conservación y eliminación de la documentación se realizará
conforme a la normativa aplicable.</p>

<h2>13. RESPONSABILIDAD</h2>
<p>EN PLAZO responderá de la correcta prestación de los servicios expresamente contratados,
actuando con la diligencia profesional correspondiente. EN PLAZO no responderá de las
consecuencias derivadas de información o documentación incorrecta o incompleta facilitada por el
CLIENTE, de la falta de instrucciones o autorizaciones necesarias, de actuaciones realizadas
directamente por el CLIENTE o terceros, de incidencias ajenas a su actuación o de las decisiones
adoptadas por las Administraciones Públicas. Esta cláusula se aplicará sin perjuicio de las
responsabilidades que legalmente no puedan excluirse o limitarse.</p>

<h2>14. LEGISLACIÓN APLICABLE</h2>
<p>El presente contrato se regirá por la legislación española que resulte aplicable. En caso de tratarse
de un consumidor, serán de aplicación las normas imperativas de protección de consumidores que
correspondan. Para cualquier cuestión derivada del contrato, las partes se someterán a los
juzgados y tribunales que resulten competentes conforme a la legislación aplicable.</p>

<hr>
<h2>FIRMA DE LAS PARTES</h2>
<div class="firma-bloque">
  <p><strong>{{ emisor.nombre }}</strong><br>CIF: {{ emisor.cif }}</p>
  <div class="firma-linea"></div>
  <p>Firma</p>
</div>
<div class="firma-bloque">
  <p><strong>EL CLIENTE</strong></p>
  <div class="campo"><span class="label">Nombre / Razón social:</span> {{ cliente.nombre_razon_social }}</div>
  <div class="campo"><span class="label">DNI / NIF / CIF:</span> {{ cliente.cif_nif }}</div>
  <div class="firma-linea"></div>
  <p>Firma</p>
</div>
</div>
"""


def upgrade() -> None:
    plantillas = sa.table(
        "plantillas_documento",
        sa.column("tipo", sa.String), sa.column("nombre", sa.String),
        sa.column("contenido_html", sa.Text), sa.column("version", sa.Integer),
        sa.column("activo", sa.Boolean),
    )
    op.execute(plantillas.update().where(plantillas.c.tipo == "contrato").values(activo=False))
    op.bulk_insert(plantillas, [{
        "tipo": "contrato", "nombre": "Contrato En Plazo — Control y Gestión Administrativa",
        "contenido_html": CONTRATO_EN_PLAZO, "version": 2, "activo": True,
    }])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plantillas_documento WHERE tipo = 'contrato' AND version = 2"))
    op.execute(sa.text("UPDATE plantillas_documento SET activo = true WHERE tipo = 'contrato' AND version = 1"))
