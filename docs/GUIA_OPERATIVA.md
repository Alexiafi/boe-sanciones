# Guía operativa — puesta en marcha real

Este documento es para Judit (o quien opere el sistema): describe, paso a paso, qué hay que aportar antes de
usar cada función en serio y qué botón/endpoint dispara cada operación real. **Nada de lo descrito aquí se
ejecuta solo** — cada acción con coste o efecto externo exige una confirmación explícita en el momento.

## 0. Antes de arrancar

```bash
cp .env.example .env
docker compose up --build
```

Con la configuración de fábrica (`.env.example` sin rellenar) el sistema funciona en local, sin tocar
ningún servicio externo: nada de OpenAI, nada de backfill, nada de email, nada de enriquecimiento. Es seguro
dejarlo así mientras se familiariza con la herramienta.

## 1. Captación diaria (ya activa)

El scraping diario del BOE se ejecuta solo (Celery Beat, 07:30 y 19:30 hora de Madrid) y **no tiene coste**:
usa la API pública del BOE y el clasificador por reglas, sin IA. Lo único que cuesta dinero es la
**extracción estructurada** (rellenar automáticamente nombre/CIF/importe/etc. desde el texto), que está
desactivada por defecto.

**Para activarla en producción**:
1. Consigue una API key de OpenAI y ponla en `OPENAI_API_KEY`.
2. Pon `OPENAI_EXTRACTION_ENABLED=true`.
3. Desde "Operación" en la web, marca "Permitir extracción OpenAI" al lanzar un scraping manual, o deja que
   el beat programado la use (revisa `OPENAI_EXTRACTION_MAX_DOCUMENTS_PER_RUN` para acotar el gasto por
   ejecución).

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
`HISTORICO_EXTRACCION_MAX_DOCS_POR_PETICION` (3 por defecto).

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
| `EMISOR_IVA_PORCENTAJE` | Tipo de IVA aplicable (por defecto 21%) |
| `FACTURA_SERIE` | Prefijo de numeración de factura (p. ej. `FAC`); si ya facturas y quieres continuidad, dínoslo para ajustar el contador inicial |

### 3.2. El texto del contrato

La plantilla sembrada por defecto es **explícitamente provisional** (lleva un aviso visible en el propio
PDF). Antes de enviar un contrato real:
1. Manda el texto definitivo del contrato (qué es fijo, qué cambia por cliente además de CIF y precio).
2. Lo cargamos vía `PATCH /api/documentos-comerciales/plantillas/{id}` (o lo hacemos por ti).
3. Verás en la pantalla de documentos si la plantilla activa sigue marcada como "provisional" — no la uses
   con clientes reales hasta que deje de estarlo.

### 3.3. Generar y enviar

1. Desde la ficha del cliente, rellena precio (contrato) o cuantía y concepto (factura) y pulsa "Generar".
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

## 4. Enriquecimiento de contacto (sesión 2, recordatorio)

Sigue el mismo patrón: desactivado por defecto, cascada de proveedores documentada en el README, activable
con `ENRICHMENT_ENABLED=true` y un proveedor configurado. Recomendado: DataForSEO (bajo coste, saldo
prepago) o Serper (2.500 consultas gratis). Ver README §"Enriquecimiento de contacto".

## 5. Resumen: qué requiere tu confirmación explícita cada vez

| Acción | Puerta permanente (`.env`) | Confirmación por petición |
|---|---|---|
| Extracción OpenAI (diaria u on-demand) | `OPENAI_EXTRACTION_ENABLED=true` + API key | Checkbox/flag `permitir_extraccion_pago` en cada lanzamiento |
| Backfill histórico | `HISTORICO_BACKFILL_ENABLED=true` | Previsualizar + token de confirmación del rango exacto |
| Consulta TEU en vivo | `TEU_PUBLIC_SEARCH_ENABLED=true` | Checkbox "incluir TEU" en cada búsqueda |
| Envío de email (contrato/factura/digest) | `EMAIL_SENDING_ENABLED=true` + SMTP configurado | `confirmar=true` en cada envío |
| Enriquecimiento en lote | `ENRICHMENT_BATCH_ENABLED=true` | `confirmar=true` en cada lote |

Ninguna de estas acciones tiene una ruta que las dispare "sola" — todas exigen que alguien, en ese momento,
las confirme.
