"""Replace contract text with the UPDATED contract the clienta sent
(CONTRATO DE PRESTACIÓN DE SERVICIOS — nueva versión, sustituye a la de
0012_contrato_en_plazo: catálogo de tarifas y clausulado distintos). Same
pattern as 0010/0012: deactivate previous active template, insert new one
as the new active version. No new context variables needed — reuses the
same servicio/precio/forma_pago/contrato.*/emisor.*/cliente.* context.

Revision ID: 0013_contrato_actualizado
Revises: 0012_contrato_en_plazo
Create Date: 2026-09-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_contrato_actualizado"
down_revision = "0012_contrato_en_plazo"
branch_labels = None
depends_on = None


CONTRATO_EN_PLAZO_V2 = r"""
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
<h1>CONTRATO DE PRESTACIÓN DE SERVICIOS</h1>

<p>En {{ contrato.lugar }}, a {{ contrato.fecha_larga }}.</p>

<h2>REUNIDOS</h2>
<p>De una parte, <strong>{{ emisor.nombre }}</strong>, con CIF <strong>{{ emisor.cif }}</strong>,
en adelante, <strong>EN PLAZO</strong>.</p>

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
<h2>1. OBJETO DEL CONTRATO</h2>
<p>El presente contrato tiene por objeto regular la prestación por EN PLAZO CONTROL Y GESTIÓN DE
NOTIFICACIONES, S.L. (en adelante, EN PLAZO) de los servicios de detección, revisión, comunicación y,
cuando corresponda, gestión de notificaciones y procedimientos administrativos que hayan sido
expresamente contratados por el CLIENTE.</p>

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
<p>Los servicios de alerta y control de EN PLAZO comprenden, según la modalidad contratada, la
búsqueda, detección, revisión y comunicación de las notificaciones y actuaciones administrativas
que puedan afectar al CLIENTE, a través de los canales y medios oficiales que correspondan,
incluidos Boletines Oficiales del Estado y/o sedes electrónicas de cada organismo.</p>
<p>Los avisos se emiten con tiempo suficiente de actuación, evitando de esta forma sanciones
elevadas derivadas de no identificación de conductor o de sanciones fuera de plazo que conlleven
intereses y no hayan sido pagadas o alegadas.</p>
<p>El canal de la revisión dependerá del servicio contratado. Las actuaciones que excedan de dicho
alcance podrán realizarse previa aceptación del CLIENTE y del presupuesto correspondiente.</p>
<p>Dentro del servicio se incluye asesoramiento legal gratuito durante la duración del contrato, en
caso de necesitar gestiones que no estén incluidas dentro del contrato se derivará al profesional
competente previa aceptación de presupuesto por el cliente.</p>
<p>Quedan fuera de los servicios ordinarios contratados las multas, sanciones, notificaciones,
deudas y procedimientos emitidos o iniciados con anterioridad a la fecha de inicio del presente
contrato, aunque sean detectados durante su vigencia. Estos expedientes podrán ser objeto de
revisión y gestión mediante el servicio de REVISIÓN DE DEUDA o mediante el presupuesto
correspondiente. Esta condición se aplicará tanto si el expediente se encuentra dentro de plazo
como si se encuentra en una fase posterior.</p>
<p>Cuando el CLIENTE tenga la condición de consumidor o usuario, serán de aplicación las
disposiciones imperativas de protección de consumidores que correspondan, prevaleciendo estas
sobre cualquier condición contractual que resulte incompatible con ellas.</p>

<hr>
<h2 style="font-size:10pt;">ALERTA BOE TRÁFICO</h2>
<p><strong>Precio: 130€ + IVA al año.</strong></p>
<p>Incluye el control y detección de multas y notificaciones del ámbito de tráfico que afecten al
CLIENTE, mediante la revisión de los correspondientes Boletines Oficiales del Estado en todo el
ámbito nacional, de cualquier organismo, y la comunicación de las incidencias detectadas vía email,
dentro de los plazos disponibles.</p>
<p>Avisos y vehículos ilimitados. Incluye la primera gestión detectada y, en caso del CLIENTE ser
empresa, queda incluido en el servicio su administrador.</p>

<hr>
<h2 style="font-size:10pt;">GESTIÓN TRÁFICO BOE</h2>
<p><strong>Precio: 235 € + IVA al año.</strong></p>
<p>Incluye todos los servicios de ALERTA TRÁFICO, e incluye además la gestión (identificación de
conductor, recurso, carta de pago bonificada, recurso extraordinario…) de las notificaciones
publicadas que puedan afectar a la empresa en todo el ámbito de tráfico.</p>
<p>Incluye todas las matrículas de la empresa y la gestión de hasta 15 incidencias anuales. En caso
de alcanzar las gestiones contratadas, podrán contratarse 15 gestiones adicionales por 100 € +
IVA.</p>
<p>El servicio de gestión para personas físicas es de 160€ + IVA anual. Este servicio no aplica para
transporte terrestre, teniendo una tarifa especial de 299€ + IVA al año.</p>

<hr>
<h2 style="font-size:10pt;">ALERTA 360</h2>
<p><strong>Suplemento para clientes: 90 € + IVA al año.</strong></p>
<p>Servicio complementario de alerta sobre notificaciones y comunicaciones administrativas
distintas de tráfico, incluyendo, según corresponda, impuestos, tasas, requerimientos,
comparecencias, deudas, embargos y otras comunicaciones de las Administraciones Públicas.</p>
<p>ALERTA 360 comprende el control y aviso de todos los ámbitos (Laboral y Seguridad Social,
Medioambiente, Sanidad, Consumo, Fiscal, Tributario, Urbanístico…) pero no la gestión de dichas
actuaciones salvo contratación específica.</p>
<p>En caso de no ser cliente, el coste de este servicio es de 120€ + IVA anual, incluyendo una
primera gestión.</p>

<hr>
<h2 style="font-size:10pt;">GESTIÓN FLOTAS</h2>
<p>Servicio aplicable a partir de 7 vehículos.</p>
<p>Incluye la detección y seguimiento de multas y notificaciones de tráfico, identificación y
gestión de incidencias, comunicaciones, trámites administrativos y seguimiento de los expedientes
relacionados con los vehículos incluidos en el servicio.</p>
<p><strong>Precio: 75 € + IVA por matrícula / año. 90€ + IVA transporte terrestre.</strong></p>
<p>Las actuaciones que, por su naturaleza, requieran servicios profesionales especializados o
excedan del alcance contratado serán comunicadas previamente al CLIENTE.</p>

<hr>
<h2 style="font-size:10pt;">GESTIÓN SEDES 360</h2>
<p><strong>Precio: 226 € + IVA al año.</strong></p>
<p>Servicio aplicable solo a clientes que ya tengan otro servicio contratado.</p>
<p>La gestión integral que permite al CLIENTE ampliar el servicio de alerta mediante la revisión y
gestión de las notificaciones y actuaciones administrativas puestas a disposición a través de los
diferentes sedes oficiales de los organismos públicos.</p>
<p>El servicio se lleva a cabo mediante el certificado digital del CLIENTE o mediante el mecanismo
de representación electrónica que corresponda, siempre que el CLIENTE haya facilitado la
autorización y medios necesarios. Cualquier apoderamiento, autorización o medio de representación
facilitado a EN PLAZO quedará limitado a las actuaciones necesarias para la prestación de los
servicios expresamente contratados. No se entenderá otorgada una autorización general para
acceder o realizar actuaciones ajenas al objeto del contrato.</p>
<p>La GESTIÓN INTEGRAL incluye dar de alta en todas las sedes y descarga diaria de las mismas,
vehículos y avisos ilimitados y hasta 25 gestiones administrativas al año. Una vez alcanzado el
límite, podrán contratarse 15 gestiones adicionales por 100 € + IVA.</p>

<hr>
<h2 style="font-size:10pt;">REVISIÓN DE EXPEDIENTES ANTERIOR AL CONTRATO</h2>
<p>EN PLAZO realizará una búsqueda jurídica gratuita de expedientes anteriores al contrato y las
deudas o expedientes en plazo detectados se le comunicarán al CLIENTE, así como las posibles vías
de actuación.</p>
<p>Si el CLIENTE solicita que EN PLAZO realice gestiones como: identificación del conductor,
presentación de alegaciones o recursos, pago o solicitud de fraccionamiento, los honorarios serán
del 10 % del importe total de los expedientes gestionados + IVA. El resultado dependerá de la
Administración competente.</p>
<p>Si el CLIENTE no desea contratar la gestión, podrá solicitar un informe con los expedientes
detectados, su situación y las posibles actuaciones, por 75€ + IVA.</p>

<hr>
<h2>4. PRESTACIÓN DEL SERVICIO Y CONTROL DE PLAZOS</h2>
<p>EN PLAZO realizará las actuaciones correspondientes al servicio contratado utilizando los medios
y sistemas adecuados para su prestación. La revisión de las notificaciones se realizará
individualmente con el objetivo de identificar la existencia de plazos administrativos y facilitar
al CLIENTE su conocimiento y seguimiento.</p>
<p>El CLIENTE deberá facilitar la información, documentación, instrucciones y autorizaciones
necesarias para realizar las actuaciones contratadas. Cuando una actuación requiera respuesta o
documentación del CLIENTE y esta no sea facilitada a tiempo, EN PLAZO no podrá garantizar su
realización dentro del plazo administrativo correspondiente.</p>
<p>Los avisos enviados por las Administraciones Públicas al correo electrónico o dispositivo
indicado por el interesado tienen carácter informativo y su falta de recepción no impide, por sí
sola, la validez de la notificación.</p>

<h2>5. REPRESENTACIÓN Y AUTORIZACIONES</h2>
<p>Determinadas actuaciones ante las Administraciones Públicas requieren identificación,
autorización o representación del interesado. Cuando sea necesario, el CLIENTE facilitará el
correspondiente apoderamiento, autorización, certificado digital o sistema de representación
electrónica válido.</p>
<p>EN PLAZO no solicitará al CLIENTE sus contraseñas personales ni utilizará mecanismos de acceso
que no estén autorizados. La contratación del servicio no sustituye las autorizaciones que pueda
exigir una Administración para una actuación concreta.</p>

<h2>6. COMUNICACIONES</h2>
<p>Las comunicaciones entre EN PLAZO y el CLIENTE podrán realizarse mediante correo electrónico,
WhatsApp, teléfono u otros medios acordados. El CLIENTE deberá mantener actualizados sus datos de
contacto. Las comunicaciones realizadas por EN PLAZO tienen por finalidad informar al CLIENTE y
facilitar la gestión del servicio contratado, sin sustituir las notificaciones oficiales de las
Administraciones Públicas.</p>

<h2>7. RESULTADO DE LAS ACTUACIONES</h2>
<p>EN PLAZO realizará las actuaciones contratadas con la diligencia profesional correspondiente. La
resolución de los procedimientos corresponde al organismo o Administración competente. Por ello,
EN PLAZO no garantiza la aceptación de recursos, alegaciones, solicitudes, identificaciones,
aplazamientos, paralizaciones u otras actuaciones presentadas ante una Administración.</p>

<h2>8. PROTECCIÓN DE DATOS Y CONFIDENCIALIDAD</h2>
<p>EN PLAZO tratará los datos personales necesarios para prestar los servicios contratados de
conformidad con el Reglamento General de Protección de Datos, la normativa española aplicable y
demás legislación vigente. La condición de EN PLAZO como responsable o encargado del tratamiento
se determinará atendiendo a la naturaleza y finalidad de cada tratamiento. Cuando EN PLAZO actúe
como encargado del tratamiento por cuenta del CLIENTE, se formalizará, cuando corresponda, el
correspondiente Anexo de Encargo de Tratamiento de Datos Personales.</p>
<p>EN PLAZO podrá tratar, entre otros, datos identificativos, datos de contacto, datos relativos a
vehículos, multas, sanciones, expedientes y procedimientos administrativos necesarios para la
prestación del servicio. La información y documentación del CLIENTE será tratada de forma
confidencial y se aplicarán las medidas de seguridad exigibles conforme a la normativa vigente.</p>

<h2>9. PRECIO Y FORMA DE PAGO</h2>
<p>El precio aplicable será el indicado en el apartado SERVICIO CONTRATADO. El pago podrá
realizarse mediante transferencia bancaria, tarjeta a través de TPV u otro medio acordado entre las
partes. Los pagos realizados mediante TPV corresponderán exclusivamente al importe previamente
aceptado por el CLIENTE. No se realizarán cargos adicionales o recurrentes en la tarjeta sin
autorización expresa del CLIENTE. Las ampliaciones de servicio, bloques adicionales o actuaciones
no incluidas serán comunicadas al CLIENTE antes de su contratación.</p>

<h2>10. DURACIÓN Y RENOVACIÓN</h2>
<p>El contrato tendrá una duración de 12 meses desde la fecha de inicio indicada. Podrá renovarse
por periodos sucesivos de 12 meses previa aceptación del cliente.</p>

<h2>11. FINALIZACIÓN DEL SERVICIO</h2>
<p>Finalizado el contrato, EN PLAZO dejará de iniciar nuevas actuaciones no incluidas en el periodo
contratado. Los asuntos que se encuentren en curso podrán ser coordinados con el CLIENTE o con los
profesionales que este designe, teniendo en cuenta el estado del procedimiento y las obligaciones
legales aplicables. La conservación y eliminación de la documentación se realizará conforme a la
normativa aplicable.</p>

<h2>12. RESPONSABILIDAD</h2>
<p>EN PLAZO responderá de la correcta prestación de los servicios expresamente contratados,
actuando con la diligencia profesional correspondiente. EN PLAZO no responderá de las
consecuencias derivadas de información o documentación incorrecta o incompleta facilitada por el
CLIENTE, de la falta de instrucciones o autorizaciones necesarias, de actuaciones realizadas
directamente por el CLIENTE o terceros, de incidencias ajenas a su actuación o de las decisiones
adoptadas por las Administraciones Públicas. Esta cláusula se aplicará sin perjuicio de las
responsabilidades que legalmente no puedan excluirse o limitarse.</p>

<h2>13. LEGISLACIÓN APLICABLE</h2>
<p>El presente contrato se regirá por la legislación española que resulte aplicable. En materia de
notificaciones administrativas, las partes tendrán en consideración, entre otras normas aplicables,
la Ley 39/2015, de 1 de octubre, del Procedimiento Administrativo Común de las Administraciones
Públicas, especialmente sus disposiciones relativas a las notificaciones y publicaciones, así como
el Real Decreto 203/2021, de 30 de marzo, en lo relativo a la actuación y funcionamiento del sector
público por medios electrónicos. En caso de tratarse de un consumidor, serán de aplicación las
normas imperativas de protección de consumidores que correspondan. Para cualquier cuestión
derivada del contrato, las partes se someterán a los juzgados y tribunales que resulten competentes
conforme a la legislación aplicable.</p>

<hr>
<h2>ACEPTACIÓN DEL CLIENTE</h2>
<p>El CLIENTE declara haber leído y aceptado las condiciones del presente contrato y del servicio
contratado. La aceptación podrá realizarse mediante firma manuscrita del presente documento,
firma electrónica o mediante respuesta de conformidad por parte del CLIENTE al correo electrónico
remitido por EN PLAZO, donde se indican los datos de servicio contratado. La aceptación realizada
por cualquiera de estos medios, junto con la identificación del CLIENTE y la conservación de la
documentación y comunicaciones intercambiadas, acreditará la contratación del servicio.</p>

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
        "tipo": "contrato", "nombre": "Contrato En Plazo — Prestación de Servicios (v2)",
        "contenido_html": CONTRATO_EN_PLAZO_V2, "version": 3, "activo": True,
    }])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plantillas_documento WHERE tipo = 'contrato' AND version = 3"))
    op.execute(sa.text("UPDATE plantillas_documento SET activo = true WHERE tipo = 'contrato' AND version = 2"))
