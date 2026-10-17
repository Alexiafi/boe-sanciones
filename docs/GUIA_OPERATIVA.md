# Guía operativa — puesta en marcha real

Este documento es para Judit (o quien opere el sistema): describe, paso a paso, qué hay que aportar antes de
usar cada función en serio y qué botón/endpoint dispara cada operación real. **Nada de lo descrito aquí se
ejecuta solo** — cada acción con coste o efecto externo exige una confirmación explícita en el momento.

## 0. Antes de arrancar

```bash
cp .env.example .env
docker compose up --build
```

### 0.1. Actualizar a una versión nueva

**Instalación conectada a git (lo habitual desde octubre de 2026).** Con Docker Desktop abierto, doble clic en
`ACTUALIZAR.bat` en la carpeta de la instalación. Descarga la última versión publicada (rama `produccion`, solo esa
versión, sin historial), hace copia de seguridad de la base de datos y del código en
`C:\Users\<usuario>\boe-sanciones-copias`, pone el código nuevo, reconstruye, aplica las migraciones y comprueba
que no falta ningún cliente ni contrato/factura. Si ya está al día, lo dice y no toca nada. **El `.env` y
`backend\data` (contratos y facturas) no se tocan nunca**: git no los gestiona. Si algo sale mal, `VOLVER_ATRAS.bat`
restaura la última copia. La conexión se hace una sola vez con `CONECTAR.bat` (paquete aparte con la clave de
solo lectura): instala Git si falta, conecta la carpeta existente y lanza la primera actualización.

**Instalación por zip (la anterior).** Cada versión se entrega como un zip (`boe-sanciones-AAAA-MM-DD.zip`) que ya trae el `.env` preparado. Se descomprime
en cualquier sitio (p. ej. el Escritorio o Descargas) y, con Docker Desktop abierto, se hace doble clic en
`ACTUALIZAR.bat` (si no funciona: PowerShell en esa carpeta y
`powershell -ExecutionPolicy Bypass -File .\actualizar.ps1`).

El script encuentra solo la instalación existente y, antes de tocar nada, enseña qué cambia en el `.env` y pide
confirmación. Después: copia de seguridad de la base de datos y del código actual (en `~/boe-sanciones-copias`),
pone el código y el `.env` nuevos, reconstruye todo, aplica las migraciones y comprueba que no falta ningún
cliente ni contrato/factura. **La base de datos y `backend/data` (contratos y facturas ya generados) no se tocan.**
Si algo sale mal, `VOLVER_ATRAS.bat` restaura la última copia (están en `C:\Users\<usuario>\boe-sanciones-copias`).

No copies la carpeta nueva a mano encima de la antigua y **no uses `docker compose down -v`**: el `-v` borra la base
de datos. Detalles del `.env` (modelo de OpenAI, concurrencia…): ver §1.

### 0.2. Que arranque solo al encender el ordenador

Todos los servicios llevan `restart: unless-stopped`: Docker los vuelve a levantar solo cuando arranca. Lo único
que hace falta es que **Docker Desktop se abra al iniciar sesión** (Docker Desktop → Settings → General →
*Start Docker Desktop when you sign in to your computer*). Con eso, al encender el ordenador no hay que abrir
Docker ni "activar el backend": en un par de minutos `http://localhost:3000` responde y la captación se pone al
día sola (al arrancar el worker revisa los últimos 10 días).

Importante: si se **apaga o se duerme** el ordenador a las 7:00, la captación de esa mañana no corre hasta que
vuelve a estar encendido; en cuanto arranca, trae lo pendiente (primero el día más reciente).

Con la configuración de fábrica (`.env.example` sin rellenar) el sistema funciona en local, sin tocar
ningún servicio externo: nada de OpenAI, nada de backfill, nada de email, nada de enriquecimiento. Es seguro
dejarlo así mientras se familiariza con la herramienta.

## 1. Captación diaria (ya activa)

La captación del BOE y del TEU se ejecuta sola (Celery Beat) **cada 30 minutos entre las 07:00 y las 11:30 y cada
hora hasta las 21:30, hora de Madrid** (para tener las multas del día a primera hora), y además **al arrancar el
software**. Cada pasada es **incremental**: solo descarga lo que aún no tiene (por ejemplo, el suplemento de
notificaciones del TEU si salió más tarde que el BOE) y solo extrae lo que falta; si no hay nada nuevo no hace nada
ni deja ejecuciones vacías. Si el BOE todavía no ha publicado la edición lo anota como "todavía no publicado" y
reintenta en la siguiente pasada.

**Cuánto tarda**: la descarga de un día completo (≈600–800 documentos entre BOE y TEU) tarda **1–2 minutos** (descarga
en paralelo) y la extracción con OpenAI se hace con varios documentos a la vez (`OPENAI_CONCURRENCY`, 6 por
defecto): del orden de 10–15 minutos en un día normal, en vez de las 3+ horas de la primera versión, que llamaba a
OpenAI de uno en uno. Los avisos de **tráfico** (Jefaturas de Tráfico, denuncias, "circulación e incidencias en la
vía pública"…) se extraen **los primeros**, para poder empezar a llamar cuanto antes. En "Operación" cada ejecución
en curso muestra su fase y su progreso (p. ej. «Extrayendo datos con OpenAI · 230/610»). Una ejecución solo se da
por colgada si lleva más de 20 minutos sin dar señales de vida (antes se marcaba a las 3 horas aunque siguiera
trabajando).

**Si algo falla**: un documento que falla se reintenta solo (2 veces seguidas y, pasadas 4 horas, hasta 2 más); si
OpenAI falla 5 veces seguidas (clave revocada, saldo agotado, caída) la extracción se detiene en vez de gastar
reintentos con todo el día, y los documentos no intentados quedan pendientes para la siguiente pasada. Los días de
los últimos **10** que se quedaron a medias se retoman solos (3 veces al día y al arrancar), empezando por el más
reciente; para un día más antiguo, "Operación" → *Lanzar captación* con esa fecha y «Forzar». Esa misma revisión
se puede lanzar a mano desde "Operación" → **Ponerse al día**.

La captación en sí **no tiene coste** (API pública del BOE + clasificador por reglas). Lo que cuesta dinero es la
**extracción estructurada** con OpenAI (nombre/CIF/importe/expediente… de cada sanción), que es lo que hace que
las multas del día aparezcan en el "Panel de Multas".

**Cómo se controla**:
1. Puerta permanente, en `.env`: `OPENAI_API_KEY` + `OPENAI_EXTRACTION_ENABLED=true`. Sin esto no se llama a
   OpenAI nunca, decida lo que decida la web.
2. Todo lo demás se decide **desde la web, en "Configuración"**, sin reiniciar nada:
   - **Extraer automáticamente cada día** (activado por defecto): las ejecuciones programadas extraen solas.
     Desactivado, solo indexan y hay que lanzar la extracción a mano desde "Operación" marcando "Permitir
     extracción OpenAI".
   - **Modo de extracción diaria**: *tiempo real* (una llamada por documento, resultados en minutos) o
     *batch* (Batch API de OpenAI: mismo modelo y mismos resultados a ~la mitad de precio, pero los datos llegan
     cuando OpenAI termina — normalmente en menos de una hora, máximo 24 h). Se puede cambiar cuando se quiera;
     aplica a la siguiente ejecución.
   - **Modo del histórico de clientes**: lo mismo para la extracción bajo demanda desde la ficha de un cliente
     (por defecto *batch*, nadie la espera al momento).
   - **Topes por ejecución**: máximo de documentos enviados a OpenAI y máximo de avisos del TEU descargados
     (el TEU publica ~2.700–2.900 avisos al día, de los que ~600–800 son sancionadores/de tráfico y se descargan).
3. **Coste de OpenAI** (todo en `.env`): el modelo por defecto es `gpt-5.4-nano` (≈4 veces más barato que
   `gpt-5.4-mini`) con `OPENAI_REASONING_EFFORT=low` (los modelos gpt-5 «razonan» y cobran esos tokens; al
   nivel por defecto cada documento gastaba miles de tokens de razonamiento). Además el texto de los PDF se
   limpia de la marca de agua vertical del BOE (una letra por línea) antes de enviarse. Si un día los resultados
   de `nano` no son buenos, subir `OPENAI_MODEL=gpt-5.4-mini` y reiniciar `backend` y `celery-worker`.
   Para bajar aún más el coste: modo *batch* (mitad de precio).
4. Los lotes batch se comprueban solos cada 5 minutos y se ven en "Operación" → **Lotes OpenAI**; al completarse,
   las sanciones aparecen en el panel, se avisa en Notificaciones y se asignan a los clientes existentes exactamente
   igual que en tiempo real.

## 2. Histórico de hasta 4 años

### 2.1. Lo que ya ocurre sin que hagas nada

Cada vez que corre el scraping diario, el documento que descarga también se indexa (gratis, sin IA) en el
histórico. Con el tiempo, esto por sí solo va construyendo cobertura — revisa `GET /api/historico/cobertura`
o la pantalla "Historial" para ver cuánto hay indexado.

### 2.2. Backfill manual (traer documentos antiguos)

**Esto es una acción real que tú debes lanzar explícitamente** — nunca ocurre sola.

1. Activa la puerta general: `HISTORICO_BACKFILL_ENABLED=true` en `.env` y reinicia el backend.
2. En la pantalla "Operación", elige un rango de fechas (recomendado: empezar por rangos pequeños, un mes o
   dos) y pulsa **"Previsualizar rango"**. Esto **no descarga nada** — solo calcula cuántos días y
   documentos estimados va a procesar y te lo muestra, junto con un aviso.
3. Revisa la previsualización. Si te parece bien, pulsa **"Confirmar y lanzar"**. Solo entonces empieza a
   descargar.
4. El backfill avanza por lotes acotados (`HISTORICO_BACKFILL_MAX_DIAS_POR_LOTE` /
   `HISTORICO_BACKFILL_MAX_DOCS_POR_LOTE`, 5 días / 200 documentos por defecto). Si se interrumpe (cierre del
   contenedor, reinicio), la siguiente vez que lo lances con el mismo rango **continúa donde lo dejó**, sin
   repetir trabajo.
5. El progreso se ve en tiempo real en la misma pantalla ("Progreso (reanudable)").

**Recomendación para llegar a los 4 años completos**: no lo hagas de una sentada. Lanza el rango más
reciente primero (el más útil para clientes nuevos) y ve ampliando hacia atrás en sesiones sucesivas — cada
una es una decisión tuya, con su propia previsualización.

**Coste**: cero en dinero (no usa OpenAI). Sí consume tiempo y ancho de banda contra boe.es — por eso está
acotado por lotes y requiere confirmación explícita.

### 2.3. Consulta pública del TEU en vivo (opcional)

Por defecto, la búsqueda de histórico de un cliente solo mira el índice propio. Si además quieres consultar
en vivo el buscador público del TEU (limitado a los últimos 90 días, ver `docs/LIMITES.md`):

1. Pon `TEU_PUBLIC_SEARCH_ENABLED=true` y `TEU_PUBLIC_SEARCH_PROVIDER=http`.
2. En la ficha de cliente o en "Consulta DNI/CIF", marca la casilla "Incluir búsqueda pública TEU (en vivo)"
   antes de buscar.

### 2.4. Extracción estructurada sobre histórico

Cuando encuentres documentos de interés en el histórico de un cliente, puedes pedir que se extraigan sus
datos con IA (mismas puertas que la extracción diaria: `OPENAI_EXTRACTION_ENABLED=true` + API key).
Selecciona los documentos en la ficha del cliente y pulsa "Extraer seleccionados" — el límite por petición es
`HISTORICO_EXTRACCION_MAX_DOCS_POR_PETICION` (3 por defecto). Con el modo del histórico en *batch*
("Configuración"), la petición se envía como lote y los datos aparecen en la ficha cuando OpenAI termina.

### 2.5. Buscar por DNI/CIF

Hay tres sitios y los tres buscan **por DNI/CIF con cualquier formato** (`12.345.678-z`, `b 12345678`…):

- **Panel de Multas** → campo «Búsqueda»: al escribir un DNI/CIF/nombre busca en **todas las fechas** (sin el
  límite de 30 días) y también por el nombre del cliente. Filtros útiles: *Cliente* (ya son clientes / aún no),
  *Gestión previa* (otro aviso del mismo DNI/CIF ya se contactó) y *Teléfono* (solo con teléfono).
- **Consulta DNI/CIF** (menú lateral): panel + índice histórico.
- La ficha de cada aviso muestra, abajo, **«Mismo titular · otros avisos»**.

Qué encuentra depende de lo que haya guardado el sistema: **solo lo captado desde que está instalado** más lo que se
traiga con el backfill (§2.2). El BOE ordinario enmascara el DNI (`***4567**`), así que ahí la búsqueda es por nombre.
Para poder ofrecer servicio por los DNI de administradores hace falta lanzar el backfill de §2.2 (una vez, con tu
confirmación): sin él, el histórico solo contiene lo captado desde la instalación.

### 2.6. Consulta por DNI/CIF y reindexado

"Consulta DNI/CIF" busca en dos sitios: las **sanciones ya extraídas** del panel (por identificador, matrícula o
nombre, ignorando puntos, guiones y acentos) y los **documentos del índice histórico**. Los documentos que la
captación diaria descargó antes de que existiera el índice se añaden a él gratis (sin red ni OpenAI) al arrancar
el software; también se puede forzar desde "Operación" → **Reindexar ahora**.

Al pulsar "Buscar histórico" en la ficha de un cliente, además de buscar en el índice se **asignan al cliente las
sanciones del panel** cuyo identificador sea el suyo o el de alguno de sus vínculos.

### 2.7. Vínculos con ficha propia (administrador, filial…)

Desde la ficha de un cliente, cada vínculo tiene el botón **"Convertir en cliente"**: crea una ficha de cliente
propia para esa persona/empresa (con sus datos de contacto, sus sanciones y su histórico), conserva el vínculo en
ambas fichas y mueve a la nueva las sanciones que ya estuvieran asignadas a ese vínculo. A partir de ahí, las
sanciones nuevas con su DNI/CIF van a su propia ficha. Para Judit son dos clientes distintos.

## 3. Documentos comerciales (contrato y factura)

**No generes documentos reales hasta completar esto.** El sistema te avisará con una lista exacta de lo que
falta si intentas generar antes de tiempo.

### 3.1. Datos que debes aportar

| Variable | Qué es |
|---|---|
| `EMISOR_NOMBRE` | Tu nombre o razón social como emisora |
| `EMISOR_CIF` | Tu CIF |
| `EMISOR_DIRECCION` | Tu dirección fiscal |
| `EMISOR_EMAIL` | Email de contacto del emisor (opcional pero recomendado) |
| `EMISOR_IBAN` | IBAN que aparecerá en las facturas |
| `EMISOR_IVA_PORCENTAJE` | Tipo de IVA aplicable (por defecto 21%) |
| `FACTURA_SERIE` | Prefijo de numeración de factura (p. ej. `FAC`); el número queda `SERIE-AÑO-0001`. Admite cualquier texto (incluso `2026/0072#`): el nombre del PDF se sanea solo. Si ya facturas y quieres continuidad, dínoslo para ajustar el contador inicial |
| `FACTURA_VENCIMIENTO_DIAS` | Días desde emisión hasta vencimiento (por defecto 30) |

### 3.2. El texto del contrato

La plantilla activa es el texto del **«Contrato OK» de octubre de 2026** (migración
`0017_contrato_octubre`, versión 4): partes con el domicilio social de En Plazo, catálogo de tarifas (ALERTA BOE
TRÁFICO, GESTIÓN TRÁFICO BOE, ALERTA 360, GESTIÓN FLOTAS, GESTIÓN SEDES 360, REVISIÓN DE EXPEDIENTES ANTERIOR
AL CONTRATO) y las cláusulas 1–13. Se reproduce **tal cual lo aprobó la clienta**, incluida su numeración (el
bloque de tarifas no lleva número entre la 2 y la 4) y su redacción. Los únicos campos variables son los del
cliente, el servicio, el precio, la forma de pago y las fechas. Si en algún momento hay que cambiar el texto
(nueva tarifa, cláusula distinta...), se edita vía `PATCH /api/documentos-comerciales/plantillas/{id}` (o se hace por
ti). La pantalla de documentos sigue mostrando si la plantilla activa está marcada como "provisional",
por si en el futuro se vuelve a sembrar una versión provisional.

### 3.3. Generar y enviar

1. Desde la ficha del cliente, rellena los datos del contrato (servicio contratado, precio, forma de
   pago y, opcionalmente, fecha de inicio — por defecto hoy; la fecha de fin se calcula sola a 12
   meses) o la cuantía y concepto de la factura, y pulsa "Generar".
   Si falta algo (datos del cliente, del emisor, o la plantilla), verás la lista exacta de qué falta.
2. Descarga el PDF y revísalo.
3. Para enviarlo por email, pulsa "Enviar por email". **Esto está desactivado por defecto**
   (`EMAIL_SENDING_ENABLED=false`) — verás un aviso claro si lo intentas sin activarlo.

### 3.4. Activar el envío real

1. Decide qué buzón usará el sistema para enviar (el tuyo, uno dedicado...).
2. Rellena `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`.
3. Pon `EMAIL_SENDING_ENABLED=true`.
4. **Antes de enviar nada real**, prueba primero con Mailpit (buzón de pruebas local, no sale ningún correo
   real):
   ```bash
   docker compose --profile dev-mail up -d mailpit
   ```
   Configura temporalmente `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `SMTP_USE_TLS=false`, activa
   `EMAIL_SENDING_ENABLED=true` y prueba un envío. Revisa el resultado (incluidos los adjuntos) en
   `http://localhost:8025`. Cuando estés satisfecha, cambia la configuración SMTP a tu buzón real.

## 4. Enriquecimiento de contacto (nombre y teléfono de empresas)

Se activa con `ENRICHMENT_ENABLED=true` y un proveedor en el `.env`. Con las claves de **Serper** y
**DataForSEO** puestas, se usa Serper primero (más fiable y la mitad de caro, unos 0,001 $ por búsqueda) y
DataForSEO solo si Serper falla.

Cómo busca una empresa:

1. Sin nombre en el aviso, busca el CIF tal cual y saca la razón social de los resultados que llevan ese CIF
   (eInforma, Infonif, DatosCIF…). El nombre se guarda en todos los avisos de ese CIF.
2. Busca «razón social telefono» y lee los resultados de esa empresa y su propia web (contacto, aviso legal,
   política de privacidad).
3. Solo guarda un teléfono o email si aparece **pegado al CIF o al nombre completo** de la empresa y
   lo respalda: una página con su CIF, su propia web (demostrada por el CIF o por el nombre con la misma forma
   jurídica) o dos directorios distintos que dan el mismo número. Nunca el número del propio directorio
   (cabecera, pie, «empresas consultadas»), ni el de un organismo (notificaciones, boletines, listas), ni un
   900/902, ni uno que ya tienen otras empresas.

En **Configuración → Nombre y teléfono de empresas nuevas** se activa la búsqueda automática: cada 15 minutos
(07:00–21:45) busca los avisos nuevos de empresas (CIF) de la última semana, con un tope diario. Las personas
(DNI/NIE) nunca se buscan solas; se pueden buscar a mano desde su aviso.

## 5. Resumen: qué requiere tu confirmación explícita cada vez

| Acción | Puerta permanente (`.env`) | Confirmación por petición |
|---|---|---|
| Extracción OpenAI diaria automática | `OPENAI_EXTRACTION_ENABLED=true` + API key | Interruptor "Extraer automáticamente cada día" en Configuración (activado por defecto) |
| Extracción OpenAI manual u on-demand (histórico) | `OPENAI_EXTRACTION_ENABLED=true` + API key | Checkbox/flag `permitir_extraccion_pago` en cada lanzamiento |
| Backfill histórico | `HISTORICO_BACKFILL_ENABLED=true` | Previsualizar + token de confirmación del rango exacto |
| Consulta TEU en vivo | `TEU_PUBLIC_SEARCH_ENABLED=true` | Checkbox "incluir TEU" en cada búsqueda |
| Envío de email (contrato/factura/digest) | `EMAIL_SENDING_ENABLED=true` + SMTP configurado | `confirmar=true` en cada envío |
| Enriquecimiento en lote | `ENRICHMENT_BATCH_ENABLED=true` | `confirmar=true` en cada lote |

Salvo la extracción diaria automática (que es precisamente lo que se contrató: que las multas del día aparezcan
solas, y que se apaga con un interruptor en Configuración), ninguna de estas acciones tiene una ruta que las dispare
"sola" — todas exigen que alguien, en ese momento, las confirme.


## 6. Una persona, un registro (mismo DNI/CIF en varios avisos)

El BOE publica un aviso nuevo cada vez que multan a alguien, y el TEU identifica a la gente **solo por el DNI/CIF**.
Para que no sea cada aviso una isla, todo se une por el **DNI/NIE/CIF completo** (los DNI enmascarados nunca se
unen):

- Un aviso nuevo de un **cliente** (o de un vínculo suyo, p. ej. su administrador) nace ya asignado al cliente, con
  su nombre y sus datos de contacto, y genera **una sola** alerta («Nueva sanción de cliente: Acme SL»).
- Un aviso nuevo de alguien al que ya se **llamó** llega con el teléfono/email/nombre ya encontrados y con la marca
  «Contactado antes» (más las notas que escribiste en los otros avisos). No se oculta: una multa nueva puede ser una
  nueva oportunidad; la marca está para no llamar «en frío» dos veces.
- Lo que escribes en un aviso (teléfono, email, dirección, nombre, webs…) se **comparte con los demás avisos del
  mismo DNI/CIF y con la ficha del cliente**, y al revés. Marcar un aviso como *contactada/descartada* cierra los
  demás avisos abiertos de esa persona. Solo se comparte lo que realmente cambias al guardar.
- Al **convertir en cliente**, o al escribir/corregir el DNI/CIF de un cliente, todos los avisos anteriores de ese
  número pasan a ser del cliente.

## 7. Clientes: tipos, borrado y agenda

- **Cliente (contratado)**, **Solo información** (aún no es cliente: solo le envías información) e **Inactivo**
  son tres estados distintos, con filtro en «Clientes». Generar un contrato a un «Solo información» lo pasa a
  «Cliente» y rellena fecha y precio de contrato. Los «Solo información» siguen vigilados por el radar de alertas.
- **Borrar cliente** (ficha → «Borrar cliente», con confirmación): quita la ficha, notas, agenda, vínculos y
  contratos; sus avisos del BOE vuelven al Panel de Multas. **Si ya se le emitió una factura no se puede borrar**
  (hay que conservarla): márcalo como Inactivo.
- **Agenda**: en la ficha del cliente, bloque «Agenda» (llamada/email/tarea con fecha y hora, notas, atajos
  «Mañana 9:00», «En 3 días»…). El menú **Agenda** reúne todas las acciones de todos los clientes (vencidas, hoy,
  próximas, sin fecha) y el Inicio muestra cuántas hay pendientes.

## 8. Contacto: de dónde sale y por qué se descartan datos

Un aviso del BOE/TEU lo escribe una administración: **el único teléfono o email que aparece es el suyo**
(«atención al ciudadano», recaudación…), nunca el del sancionado. Por eso:

- «Enriquecer contacto» **solo busca en la web** (o reutiliza lo ya registrado para el mismo DNI/CIF o en la ficha
  del cliente); nunca lee teléfonos/emails del texto del aviso ni toma nombres de listas de personas.
- La extracción con OpenAI recibe la instrucción de no usar datos del organismo, y además se descartan: números
  públicos (012, 060, 900…), emails de administraciones (`…gob.es`, `…gencat.cat`, ayuntamientos, diputaciones…)
  y cualquier teléfono/email repetido en varias personas del mismo aviso.
- Cada dato lleva su **fuente**; el enlace «fuente» solo aparece si es una web real (antes un valor interno
  apuntaba a una ruta de esta aplicación y daba 404).
- Al actualizar, una migración limpia los contactos erróneos ya guardados (los escritos a mano nunca se tocan) y
  esas oportunidades vuelven a «pendiente» para poder enriquecerse de nuevo.

## 9. Cobertura: qué se capta y qué no

Se capta todo el **BOE** y el **Tablón Edictal Único (TEU)**, donde publican (art. 44 Ley 39/2015) la DGT y las
Jefaturas de Tráfico, ayuntamientos, diputaciones forales, comunidades autónomas, Seguridad Social, etc.
De los ~2.800 avisos diarios del TEU se descargan los sancionadores, de deudas **y de tráfico** (denuncias,
circulación, estacionamiento, retirada de vehículos, pérdida de vigencia del permiso…); se dejan fuera registros de
la propiedad, notarías, padrón, subvenciones y resultados de exámenes de conducir.

**No se capta** lo que una administración publica **solo en su propio boletín** (BOP provinciales, DOGC, sedes
electrónicas): es otra fuente que habría que integrar aparte. Si una Diputación o el Servei Català de Trànsit no
aparecen, lo primero a comprobar es si esa publicación está en el TEU.

**Límite conocido**: un aviso del TEU con listas muy largas (p. ej. un PDF de la DGT con miles de filas) se envía a
OpenAI truncado a ~30.000 caracteres, por lo que de esas listas solo se extraen las primeras personas.
