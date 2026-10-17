"""Contract template: the text of "Contrato OK" (October 2026).

Judit's latest approved contract replaces the one installed by
``0013_contrato_actualizado``: the parties' block carries the issuer's registered
office, the rates catalogue is reworded (ALERTA BOE TRÁFICO, GESTIÓN TRÁFICO
BOE, ALERTA 360, GESTIÓN FLOTAS, GESTIÓN SEDES 360, REVISIÓN DE EXPEDIENTES
ANTERIOR AL CONTRATO) and the clauses are the shorter, final wording.

The wording is reproduced as approved, including its own spelling and its
numbering (the rates block has no number between clauses 2 and 4): this is
her legal text, not ours to correct. Only the per-client data are placeholders
(parties, service, price, payment, dates), exactly like the previous versions.

Same pattern as 0010/0012/0013: deactivate the previous active contract
template and insert the new one as the next version.

Revision ID: 0017_contrato_octubre
Revises: 0016_limpia_contacto_organismo
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_contrato_octubre"
down_revision = "0016_limpia_contacto_organismo"
branch_labels = None
depends_on = None


CONTRATO_EN_PLAZO_V4 = r"""
<style>
  .contrato { color: #181c1e; font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; line-height: 1.5; }
  .contrato h1 { font-size: 14pt; margin: 0 0 1em; }
  .contrato h2 { font-size: 10.5pt; margin: 1.4em 0 0.5em; }
  .contrato h3 { font-size: 10pt; margin: 1.3em 0 0.4em; text-decoration: underline; }
  .contrato p { margin: 0.55em 0; }
  .contrato .campo { margin: 0.35em 0; }
  .contrato hr { border: none; border-top: 1px solid #c4c6cf; margin: 1.1em 0; }
  .contrato .firma-linea { margin-top: 1.8em; border-top: 1px solid #181c1e; width: 60%; }
</style>
<div class="contrato">
<h1>CONTRATO DE PRESTACIÓN DE SERVICIOS</h1>

<p><strong>En {{ contrato.lugar }}, a {{ contrato.fecha_larga }}.</strong></p>

<p><strong>REUNIDOS</strong></p>

<p>De una parte, <strong>EN PLAZO CONTROL Y GESTIÓN DE NOTIFICACIONES, S.L.</strong>, con CIF
<strong>B93993376</strong>, y domicilio social en Calle Monlau 35, 08027 de Barcelona, en adelante,
<strong>EN PLAZO</strong>.</p>

<p><strong>De otra parte,</strong>D./D.ª / Empresa:</p>

<div class="campo"><strong>Nombre / Razón social:</strong> {{ cliente.nombre_razon_social }}</div>
<div class="campo"><strong>DNI / NIF / CIF:</strong> {{ cliente.cif_nif or cliente.dni_nie or "" }}</div>
<div class="campo"><strong>Domicilio:</strong> {{ cliente.direccion_fiscal }}</div>
<div class="campo"><strong>Teléfono:</strong> {{ cliente.telefono or "" }}</div>
<div class="campo"><strong>Email:</strong> {{ cliente.email or "" }}</div>

<p>En adelante, <strong>EL CLIENTE</strong>.</p>

<p>Ambas partes se reconocen capacidad suficiente para contratar y acuerdan las siguientes:</p>

<p><strong>CONDICIONES</strong></p>

<p><strong>1. OBJETO DEL CONTRATO</strong></p>

<p>El presente contrato tiene por objeto regular la prestación por <strong>EN PLAZO CONTROL Y GESTIÓN DE
NOTIFICACIONES, S.L.</strong> (en adelante, <strong>EN PLAZO</strong>) de los servicios de detección,
revisión, comunicación y, cuando corresponda, gestión de notificaciones en vía administrativa, que
hayan sido expresamente contratados por el CLIENTE.</p>

<div class="campo"><strong>Servicio contratado:</strong> {{ servicio }}</div>
<div class="campo"><strong>Precio:</strong> {{ precio }} € + IVA</div>
<div class="campo"><strong>Forma de pago:</strong> {{ forma_pago }}</div>
<div class="campo"><strong>Fecha de inicio:</strong> {{ contrato.fecha_inicio }}</div>
<div class="campo"><strong>Fecha de finalización:</strong> {{ contrato.fecha_fin }}</div>
<div class="campo"><strong>Duración:</strong> 12 meses.</div>

<p>El CLIENTE contrata exclusivamente el servicio indicado en este apartado, con el alcance y
condiciones establecidos en el presente contrato.</p>

<hr>

<p><strong>2. SERVICIOS Y TARIFAS</strong></p>

<p><strong>Los servicios de alerta y control de EN PLAZO comprenden, según la modalidad contratada, la
búsqueda, detección, revisión, comunicación y gestión administrativa de notificaciones publicadas en
los Boletines Oficiales del Estado.</strong></p>

<p><strong>Los avisos se emiten con tiempo suficiente de actuación, evitando de esta forma sanciones
elevadas derivadas de no identificación de conductor o de sanciones fuera de plazo que conlleven
intereses y no hayan sido pagadas o alegadas.</strong></p>

<p><strong>El alcance de actuación dependerá del servicio contratado. Las actuaciones que excedan de
dicho alcance podrán realizarse previa aceptación del CLIENTE y del presupuesto
correspondiente.</strong></p>

<p><strong>En todos los servicios se incluye asesoramiento durante la duración del contrato, en caso de
necesitar gestiones que no estén incluidas dentro del contrato se derivará al profesional competente
previa aceptación de presupuesto por el cliente.</strong></p>

<p><strong><em>Quedan fuera de los servicios ordinarios contratados las multas, sanciones,
notificaciones, deudas y procedimientos emitidos o iniciados con anterioridad a la fecha de inicio del
presente contrato, aunque sean detectados durante su vigencia.</em></strong></p>

<p><em>Estos expedientes podrán ser objeto de revisión y gestión mediante el servicio de REVISIÓN DE
DEUDA o mediante el presupuesto correspondiente.</em></p>

<p>Esta condición se aplicará tanto si el expediente se encuentra dentro de plazo como si se encuentra
en una fase posterior.</p>

<p>Cuando el CLIENTE tenga la condición de consumidor o usuario, serán de aplicación las disposiciones
imperativas de protección de consumidores que correspondan, prevaleciendo estas sobre cualquier
condición contractual que resulte incompatible con ellas.</p>

<h3>ALERTA BOE TRÁFICO</h3>

<p><strong>Precio: 130€ + IVA al año.</strong></p>

<p>Incluye el control y detección de multas y notificaciones del ámbito de tráfico que afecten al
CLIENTE, mediante la revisión de los correspondientes Boletines Oficiales del Estado en todo el ámbito
nacional, de cualquier organismo, y la comunicación de las incidencias detectadas vía email, dentro de
los plazos disponible</p>

<p>Avisos y vehículos ilimitados.</p>

<p>Incluye <strong>la primera gestión</strong> detectada Y EN CASO DEL CLIENTE SER EMPRESA queda incluido
en el servicio su administrador.</p>

<hr>

<h3>GESTIÓN TRÁFICO BOE</h3>

<p><strong>Precio: 235 € + IVA al año.</strong></p>

<p>Incluye todos lo servicios de ALERTA TRÁFICO, e incluye además la gestión ( identificación de
conductor, recurso, carta de pago bonificada, recurso extraordinario…) de las notificaciones
publicadas que puedan afectar a la empresa en todo el ámbito de tráfico.</p>

<p>Incluye todas las matrículas de la empresa y la gestión de hasta <strong>15 incidencias
anuales</strong>.</p>

<p>En caso de alcanzar las gestiones contratadas, podrán contratarse <strong>15 gestiones adicionales por
100 € + IVA</strong>.</p>

<p>El servicio de gestión para personas físicas es de 160€ + IVA anual.</p>

<p>Este servicio no aplica para transporte terrestre, teniendo una tarifa especial de 299€ + IVA al
año.</p>

<hr>

<h3>ALERTA 360</h3>

<p><strong>Suplemento para clientes 90 + IVA al año.</strong></p>

<p>Servicio complementario de alerta sobre notificaciones y comunicaciones administrativas distintas de
tráfico, incluyendo, según corresponda, impuestos, tasas, requerimientos, comparecencias, deudas,
embargos y otras comunicaciones de las Administraciones Públicas.</p>

<p>ALERTA 360 comprende <strong>el control y aviso</strong>, de todos los ámbitos (Laboral y Seguridad
social, Medioambiente, Sanidad, Consumo, Fiscal, Tributario Urbanístico…) pero no la gestión de dichas
actuaciones salvo contratación específica.</p>

<p>En caso de NO SER CLIENTE el coste por este servicio es de 120€ + IVA anual, incluyendo una primera
gestión.</p>

<hr>

<h3>GESTIÓN FLOTAS</h3>

<p><strong>Servicio aplicable a partir de 7 vehículos.</strong></p>

<p>Incluye la detección y seguimiento de multas y notificaciones de tráfico, identificación y gestión de
incidencias, comunicaciones, trámites administrativos y seguimiento de los expedientes relacionados con
los vehículos incluidos en el servicio.</p>

<p><strong>Precio: 75 € + IVA por matrícula / año.<br>90€ + IVA transporte terrestre.</strong></p>

<p>Las actuaciones que, por su naturaleza, requieran servicios profesionales especializados o excedan
del alcance contratado serán comunicadas previamente al CLIENTE.</p>

<h3>GESTIÓN SEDES 360</h3>

<p><strong>Precio: 226 € + IVA al año.</strong></p>

<p>Servicio aplicable solo a clientes que ya tengan otro servicio contratado.</p>

<p>La gestión integral que permite al CLIENTE ampliar el servicio de alerta mediante la <strong>revisión
y gestión de las notificaciones y actuaciones administrativas puestas a disposición a través de los
diferentes sedes oficiales de los organismos públicos.</strong></p>

<p>El servicio se lleva a cabo <strong>mediante el certificado representante del cliente</strong>, o
salvo expresa autorización del cliente mediante su certificado digital.</p>

<p><strong>Cualquier apoderamiento, autorización o medio de representación facilitado a EN PLAZO
quedará limitado a las actuaciones necesarias para la prestación de los servicios expresamente
contratados.</strong></p>

<p>No se entenderá otorgada una autorización general para acceder o realizar actuaciones ajenas al
objeto del contrato.</p>

<p>La GESTIÓN INTEGRAL incluye dar de alta en todas las sedes y descarga diaria de las mismas ,
vehículos y avisos ilimitados y <strong>hasta 25 gestiones administrativas al año</strong>.</p>

<p>Una vez alcanzado el límite, podrán contratarse <strong>15 gestiones adicionales por 100 € +
IVA</strong>.</p>

<hr>

<h3>REVISIÓN DE EXPEDIENTES ANTERIOR AL CONTRATO</h3>

<p>EN PLAZO realizara una búsqueda jurídica gratuita de expedientes anteriores al contrato y las deudas
o expedientes en plazo detectados se le comunicarán al CLIENTE así como las posibles vías de
actuación.</p>

<p>Si el CLIENTE solicita que EN PLAZO realice gestiones como: <strong>identificación del conductor,
presentación de alegaciones o recursos, pago o solicitud de fraccionamiento</strong>, los honorarios
serán del <strong>10 % del importe total de los expedientes gestionados + IVA.</strong></p>

<p>El resultado dependerá de la Administración competente.</p>

<p>Si el CLIENTE no desea contratar la gestión, podrá solicitar un <strong>informe con los expedientes
detectados, su situación y las posibles actuaciones</strong>, por <strong>75€ + IVA</strong>.</p>

<hr>

<p><strong>4. PRESTACIÓN DEL SERVICIO Y CONTROL DE PLAZOS</strong></p>

<p>EN PLAZO realizará las actuaciones correspondientes al servicio contratado utilizando los medios y
sistemas adecuados para su prestación.</p>

<p>La revisión de las notificaciones se realizará individualmente con el objetivo de identificar la
existencia de plazos administrativos y facilitar al CLIENTE su conocimiento y seguimiento.</p>

<p>El CLIENTE deberá facilitar la información, documentación, instrucciones y autorizaciones necesarias
para realizar las actuaciones contratadas.</p>

<p>Cuando una actuación requiera respuesta o documentación del CLIENTE y esta no sea facilitada a
tiempo, EN PLAZO no podrá garantizar su realización dentro del plazo administrativo correspondiente.</p>

<p>Los avisos enviados por las Administraciones Públicas al correo electrónico o dispositivo indicado
por el interesado tienen carácter informativo y su falta de recepción no impide, por sí sola, la
validez de la notificación.</p>

<hr>

<p><strong>5. REPRESENTACIÓN Y AUTORIZACIONES</strong></p>

<p>Determinadas actuaciones ante las Administraciones Públicas requieren identificación, autorización o
representación del interesado.</p>

<p>Cuando sea necesario, el CLIENTE facilitará el correspondiente apoderamiento, autorización,
certificado digital o sistema de representación electrónica válido.</p>

<p>EN PLAZO no solicitará al CLIENTE sus contraseñas personales ni utilizará mecanismos de acceso que
no estén autorizados.</p>

<p>La contratación del servicio no sustituye las autorizaciones que pueda exigir una Administración
para una actuación concreta.</p>

<hr>

<p><strong>6. COMUNICACIONES</strong></p>

<p>Las comunicaciones entre EN PLAZO y el CLIENTE podrán realizarse mediante correo electrónico,
WhatsApp, teléfono u otros medios acordados.</p>

<p>El CLIENTE deberá mantener actualizados sus datos de contacto.</p>

<p>Las comunicaciones realizadas por EN PLAZO tienen por finalidad informar al CLIENTE y facilitar la
gestión del servicio contratado, sin sustituir las notificaciones oficiales de las Administraciones
Públicas.</p>

<hr>

<p><strong>7. RESULTADO DE LAS ACTUACIONES</strong></p>

<p>EN PLAZO realizará las actuaciones contratadas con la diligencia profesional correspondiente.</p>

<p>La resolución de los procedimientos corresponde al organismo o Administración competente.</p>

<p>Por ello, EN PLAZO no garantiza la aceptación de recursos, alegaciones, solicitudes,
identificaciones, aplazamientos, paralizaciones u otras actuaciones presentadas ante una
Administración.</p>

<hr>

<p><strong>8. PROTECCIÓN DE DATOS Y CONFIDENCIALIDAD</strong></p>

<p>EN PLAZO tratará los datos personales necesarios para prestar los servicios contratados de
conformidad con el Reglamento General de Protección de Datos, la normativa española aplicable y demás
legislación vigente.</p>

<p>La condición de EN PLAZO como <strong>responsable o encargado del tratamiento</strong> se
determinará atendiendo a la naturaleza y finalidad de cada tratamiento.</p>

<p>Cuando EN PLAZO actúe como encargado del tratamiento por cuenta del CLIENTE, se formalizará, cuando
corresponda, el correspondiente <strong>Anexo de Encargo de Tratamiento de Datos
Personales</strong>.</p>

<p>EN PLAZO podrá tratar, entre otros, datos identificativos, datos de contacto, datos relativos a
vehículos, multas, sanciones, expedientes y procedimientos administrativos necesarios para la
prestación del servicio.</p>

<p>La información y documentación del CLIENTE será tratada de forma confidencial y se aplicarán las
medidas de seguridad exigibles conforme a la normativa vigente.</p>

<hr>

<p><strong>9. PRECIO Y FORMA DE PAGO</strong></p>

<p>El precio aplicable será el indicado en el apartado <strong>SERVICIO CONTRATADO</strong>.</p>

<p>El pago podrá realizarse mediante transferencia bancaria, tarjeta a través de TPV u otro medio
acordado entre las partes.</p>

<p>Los pagos realizados mediante TPV corresponderán exclusivamente al importe previamente aceptado por
el CLIENTE.</p>

<p>No se realizarán cargos adicionales o recurrentes en la tarjeta sin autorización expresa del
CLIENTE.</p>

<p>Las ampliaciones de servicio, bloques adicionales o actuaciones no incluidas serán comunicadas al
CLIENTE antes de su contratación.</p>

<hr>

<p><strong>10. DURACIÓN Y RENOVACIÓN</strong></p>

<p>El contrato tendrá una duración de <strong>12 meses</strong> desde la fecha de inicio indicada.</p>

<p>Podrá renovarse por periodos sucesivos de 12 meses previa aceptación del cliente.</p>

<hr>

<p><strong>11. FINALIZACIÓN DEL SERVICIO</strong></p>

<p>Finalizado el contrato, EN PLAZO dejará de iniciar nuevas actuaciones no incluidas en el periodo
contratado.</p>

<p>Los asuntos que se encuentren en curso podrán ser coordinados con el CLIENTE o con los profesionales
que este designe, teniendo en cuenta el estado del procedimiento y las obligaciones legales
aplicables.</p>

<p>La conservación y eliminación de la documentación se realizará conforme a la normativa
aplicable.</p>

<hr>

<p><strong>12. RESPONSABILIDAD</strong></p>

<p>EN PLAZO responderá de la correcta prestación de los servicios expresamente contratados, actuando
con la diligencia profesional correspondiente.</p>

<p>EN PLAZO no responderá de las consecuencias derivadas de información o documentación incorrecta o
incompleta facilitada por el CLIENTE, de la falta de instrucciones o autorizaciones necesarias, de
actuaciones realizadas directamente por el CLIENTE o terceros, de incidencias ajenas a su actuación o
de las decisiones adoptadas por las Administraciones Públicas.</p>

<p>Esta cláusula se aplicará sin perjuicio de las responsabilidades que legalmente no puedan excluirse
o limitarse.</p>

<hr>

<p><strong>13. LEGISLACIÓN APLICABLE</strong></p>

<p>El presente contrato se regirá por la legislación española que resulte aplicable.</p>

<p>En materia de notificaciones administrativas, las partes tendrán en consideración, entre otras normas
aplicables, la <strong>Ley 39/2015, de 1 de octubre, del Procedimiento Administrativo Común de las
Administraciones Públicas</strong>, especialmente sus disposiciones relativas a las notificaciones y
publicaciones, así como el <strong>Real Decreto 203/2021, de 30 de marzo</strong>, en lo relativo a la
actuación y funcionamiento del sector público por medios electrónicos.</p>

<p>En caso de tratarse de un consumidor, serán de aplicación las normas imperativas de protección de
consumidores que correspondan.</p>

<p>Para cualquier cuestión derivada del contrato, las partes se someterán a los juzgados y tribunales
que resulten competentes conforme a la legislación aplicable.</p>

<hr>

<p><strong>ACEPTACIÓN DEL CLIENTE</strong></p>

<p>El CLIENTE declara haber leído y aceptado las condiciones del presente contrato y del servicio
contratado.</p>

<p><strong>La aceptación podrá realizarse mediante firma manuscrita del presente documento, firma
electrónica o mediante respuesta de conformidad por parte del CLIENTE al correo electrónico remitido
por EN PLAZO, donde se indican los datos de servicio contratado.</strong></p>

<p>La aceptación realizada por cualquiera de estos medios, junto con la identificación del CLIENTE y la
conservación de la documentación y comunicaciones intercambiadas, acreditará la contratación del
servicio.</p>

<div class="campo"><strong>Fecha de aceptación:</strong> ____ / ____ / ______</div>
<div class="campo"><strong>Nombre del cliente:</strong> {{ cliente.nombre_razon_social }}</div>
<div class="campo"><strong>Firma</strong>:</div>
<div class="firma-linea"></div>
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
        "tipo": "contrato", "nombre": "Contrato En Plazo — Prestación de Servicios (octubre 2026)",
        "contenido_html": CONTRATO_EN_PLAZO_V4, "version": 4, "activo": True,
    }])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plantillas_documento WHERE tipo = 'contrato' AND version = 4"))
    op.execute(sa.text("UPDATE plantillas_documento SET activo = true WHERE tipo = 'contrato' AND version = 3"))
