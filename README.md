# BOE Sanciones

Sistema de extraccion, gestion y seguimiento de sanciones publicadas en el Boletin Oficial del Estado (BOE).

## Arquitectura

| Servicio | Tecnologia | Puerto |
|---|---|---|
| Backend API | FastAPI + SQLAlchemy | 8000 |
| Task Queue | Celery + Redis | - |
| Scheduler | Celery Beat | - |
| Base de datos | PostgreSQL 16 | 5432 |
| Cache/Broker | Redis 7 | 6379 |
| Frontend | Next.js 16 + Tailwind v4 | 3000 |
| SearXNG (opcional) | Descubrimiento gratuito para enriquecimiento | 8080 |
| Mailpit (opcional, perfil `dev-mail`) | Buzón SMTP local de pruebas | 1025 (SMTP) / 8025 (web) |

## Requisitos

- Docker y Docker Compose
- OpenAI API key (solo cuando se habilite manualmente la extracción estructurada)
- Nada más es obligatorio: enriquecimiento, backfill histórico, envío de email y proveedores de pago están
  todos desactivados por defecto (ver `.env.example`).

## Inicio rapido

```bash
# 1. Configurar variables de entorno
cp .env.example .env
# Mantén OPENAI_EXTRACTION_ENABLED=false durante desarrollo y pruebas.

# 2. Levantar todos los servicios
docker compose up --build

# 3. Acceder
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

Para verificar la sesión 1 sin iniciar worker ni scheduler (y, por tanto, sin
consultar BOE/TEU), usa únicamente:

```bash
docker compose up -d --build postgres migrate backend frontend
```

El arranque completo también inicia Celery Beat y el worker diario. La
extracción OpenAI sigue protegida por configuración, pero ese modo sí puede
realizar ingesta real del BOE en las horas programadas.

## Funcionalidades

- **Scraping automatico**: extrae el sumario diario del BOE via API oficial cada 12 horas
- **Clasificacion por reglas**: filtra documentos sancionadores usando patrones STRONG/MEDIUM
- **Oportunidades operativas**: cada afectado persistido recibe un código único `OP-YYYY-NNNNNN`, estado y campos estructurados disponibles.
- **Extracción con IA bajo control de coste**: está desactivada por defecto. Requiere `OPENAI_EXTRACTION_ENABLED=true`, API key y confirmación explícita en el trigger manual; el límite inicial es un documento por ejecución.
- **Enriquecimiento de contacto bajo demanda** (sesión 2): busca teléfono/email en la web corporativa pública de la persona/empresa sancionada, verificando por evidencia (CIF o razón social encontrados en la página) antes de guardar nada. Desactivado por defecto; ver sección dedicada más abajo.
- **Clientes/CRM** (sesión 2): conversión idempotente de una oportunidad en cliente, ficha con notas, registro de actividad y acciones agendadas.
- **Seguimiento**: la abogada puede marcar estado de cada sancionado (pendiente, contactado, en gestion, descartado, resuelto)
- **Notificaciones**: alertas in-app y email digest cuando se detectan nuevas sanciones
- **Scraping manual**: ejecutar extraccion para una fecha concreta desde la UI
- **Histórico de hasta 4 años** (sesión 3): índice propio sin LLM (regex de DNI/NIE/CIF/matrícula + FTS por
  nombre), acumulación diaria gratuita, backfill manual acotado y reanudable, búsqueda por cliente y
  extracción estructurada on-demand. Ver sección dedicada más abajo.
- **Documentos comerciales** (sesión 3): generación de contrato y factura en PDF (WeasyPrint) a partir de
  plantillas editables, numeración de factura segura, envío por email con adjuntos (gated, nunca real por
  defecto). Ver sección dedicada más abajo.
- **Rediseño visual** (sesión 3): sistema "Minimalismo Autoritario" aplicado a todas las pantallas
  (`frontend/src/components/ui/`, tokens en `frontend/src/app/globals.css`).

## Enriquecimiento de contacto (sesión 2)

Es la pieza más crítica del producto: no un "pega la URL y te extraigo el dato", sino una búsqueda
acotada y auditable de **dónde** vive el contacto público de una persona o empresa sancionada.

- **Desactivado por defecto** (`ENRICHMENT_ENABLED=false`) y sin proveedor configurado
  (`ENRICHMENT_SEARCH_PROVIDER=none`). Ambas condiciones deben cumplirse para que se ejecute
  cualquier búsqueda; sin ellas, el endpoint devuelve 409 y ninguna prueba construye un cliente
  HTTP real (verificado activamente en `tests/test_enrichment.py`).
- **Cascada**: descubre URLs candidatas con el proveedor configurado → descarga la página (con
  timeout, límite de tamaño, `robots.txt`, rate limit por dominio y reintentos acotados) → sigue
  los enlaces "aviso legal"/"contacto" (la LSSI-CE obliga a las empresas españolas a publicar ahí
  su CIF y contacto, por eso es la página con más densidad de dato fiable) → extrae teléfono/email
  por regex → **solo persiste si hay evidencia**: el CIF/NIF del sancionado aparece en la página
  (confianza alta) o su nombre/razón social exacto aparece (confianza media, sujeta a
  `ENRICHMENT_MIN_CONFIDENCE`). Sin evidencia, el resultado es `no_encontrado` y no se escribe nada.
- **Proveedores de descubrimiento**: `fixture` (sin red, el único activo en pruebas). Investigación
  de proveedores reales verificada dos veces (2026-08-03, la segunda con `deep-research-report
  (14).md`):
  - **`dataforseo`** (recomendado, principal): API de resultados orgánicos de Google reales, coste
    efectivo ~0,002 $/consulta en modo Live, saldo prepago que no caduca. Requiere cuenta con saldo
    (recarga mínima 50 $) y `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD` (usuario/contraseña del panel,
    no una única API key).
  - **`serper`** (recomendado, respaldo): 2.500 consultas gratis sin tarjeta; después hay que
    comprar un bloque de 50.000 por 50 $ que caduca a los 6 meses, por eso es respaldo y no
    principal.
  - **`searxng`** (opcional, tercer nivel): autoalojado, sin API key, coste marginal cero pero sin
    SLA (depende de motores externos, puede sufrir CAPTCHA o bloqueos temporales).
  - **`tavily`** (**no recomendado**): sus términos (actualizados 2026-05-04) prohíben usarlo para
    "unsolicited marketing proposals" — exactamente lo que hace este enriquecimiento. No activar sin
    autorización escrita de Tavily.
  - Google Custom Search y Brave Search API se descartaron en ambas investigaciones: CSE está
    cerrado a nuevos clientes y se apaga el 1-ene-2027; Brave eliminó su capa gratuita en feb-2026.
  - Un `paid_stub` documenta la interfaz para eInforma/Google Places sin integrarlos.
- **LinkedIn**: si el descubrimiento encuentra una URL de perfil, se guarda como enlace a revisar a
  mano; nunca se descarga, se hace scraping ni login.
- **Trazabilidad**: cada intento (encontrado, no encontrado, omitido por `robots.txt` o error) queda
  registrado en `EnriquecimientoIntento` con proveedor, consulta, confianza, evidencia y coste
  estimado. La caché (`EnriquecimientoCache`) evita repetir la misma consulta.
- **Edición manual**: `PATCH /api/sanciones/{id}` con teléfono/email/web/LinkedIn marca
  `contacto_estado=manual`; el enriquecimiento automático nunca sobrescribe un contacto manual.
- **Lote**: `POST /api/enriquecimiento/lote` exige `confirmar=true` **y**
  `ENRICHMENT_BATCH_ENABLED=true`, con tope `ENRICHMENT_BATCH_MAX`.
- **Expectativa realista**: en personas jurídicas con web pública el acierto es razonable; en
  **particulares será bajo** (solo autónomos con presencia web). El respaldo manual es parte del
  producto, no un fallo del enriquecimiento automático.
- **RGPD**: solo se persiste contacto ya publicado profesionalmente por la propia entidad, con
  fuente, URL y fecha siempre guardadas, editable y borrable desde la ficha. La base de licitud
  (interés legítimo/actividad profesional) y la valoración jurídica final corresponden a la clienta.

**Coste**: en desarrollo y pruebas, cero — sin proveedor real activo y sin llamadas reales. En
producción con DataForSEO, 2.000 búsquedas/mes cuestan entre 1,20 $ (Standard) y 4 $ (Live); el
saldo de 50 $ inicial dura muchos meses a ese ritmo. Con Serper hay margen gratis (2.500 consultas)
antes de necesitar ninguna compra. Cualquier proveedor adicional de pago queda en `paid_stub`, sin
integrar.

## Histórico de hasta 4 años (sesión 3)

Diseñado para coste de desarrollo y operación prácticamente cero, siguiendo la estrategia de PLAN.md §2.3:
índice ligero sin LLM + acumulación diaria gratuita + búsqueda por cliente + extracción estructurada solo
sobre lo que interesa.

- **Indexado sin LLM**: `services/historico/patterns.py` extrae DNI/NIE/CIF (con validación de letra de
  control), matrículas (antigua/nueva, con lista de exclusión de falsos positivos) y nombres por regex —
  cero coste, cero llamadas externas. `services/historico/indexado.py` los guarda de forma idempotente por
  `boe_id` (unión de claves si el documento ya existía).
- **Acumulación diaria gratuita**: el pipeline diario (`tasks/scraping.py`) indexa en el histórico cada
  documento candidato que ya ha descargado, sin coste marginal de red ni de OpenAI
  (`HISTORICO_INDEXADO_DIARIO_ENABLED=true` por defecto). Es la única forma en que el histórico del TEU
  anterior a 90 días llegará a existir — ver limitación más abajo.
- **Backfill manual, acotado y reanudable** (`tasks/historico_backfill.py`): **nunca automático** — no está
  en Celery beat y requiere `HISTORICO_BACKFILL_ENABLED=true` **y**, en cada petición, un token de
  confirmación que codifica el rango exacto y los límites (`POST /api/historico/backfill/plan` primero,
  luego `POST /api/historico/backfill` con ese token). Progreso y reanudación via `HistoricoBackfillRun`
  (camina hacia atrás desde `fecha_hasta`, comprometiendo cursor y documentos en la misma transacción, así
  que una interrupción nunca repite ni pierde más de un día). Topes configurables
  (`HISTORICO_BACKFILL_MAX_DIAS_POR_LOTE`, `HISTORICO_BACKFILL_MAX_DOCS_POR_LOTE`). El módulo **no importa
  `app.services.extractor`** — la ausencia estructural es la garantía, no solo el flag.
- **Búsqueda por cliente** (`services/historico/busqueda.py`): exacta por CIF/DNI/matrícula (JSONB + GIN
  `jsonb_path_ops`) y por nombre normalizado (FTS `tsvector` generado, configuración `simple` para no
  mutilar apellidos, sin necesitar la extensión `unaccent`). Idempotente: repetir la búsqueda no duplica
  resultados ni pisa una extracción previa.
- **Conector TEU público opcional** (`services/historico/teu_publico.py`): apagado por defecto
  (`TEU_PUBLIC_SEARCH_ENABLED=false`), nunca automático, con adaptador `fixture` para pruebas y `http` real
  solo si se activa explícitamente.
- **Extracción on-demand** (`tasks/historico_extraccion.py`): reutiliza exactamente las mismas puertas de
  coste OpenAI que el pipeline diario. No crea oportunidades nuevas (los documentos históricos son material
  de referencia para un cliente ya existente, no una vía para inflar el panel de 30 días).
- **Limitación del TEU (importante, visible en la UI)**: el Tablón Edictal Único solo permite consulta
  pública durante **90 días** desde la publicación. Pasado ese plazo, el histórico del TEU solo contiene lo
  que este sistema haya acumulado por sí mismo desde su puesta en marcha; el BOE ordinario sí queda cubierto
  de forma indefinida. Ver `docs/LIMITES.md`.

## Documentos comerciales (sesión 3)

- **Plantillas editables en base de datos** (`plantillas_documento`, sembradas con un texto **marcado
  explícitamente como provisional** — nunca se inventa contenido contractual ni fiscal). Edítalas desde
  `PATCH /api/documentos-comerciales/plantillas/{id}` o directamente en la UI antes de emitir documentos
  reales.
- **Validación explícita de datos faltantes** (`services/documentos_comerciales.validar_estructural` /
  `validar`): antes de generar, la API devuelve la lista exacta de campos que faltan (emisor, plantilla,
  datos fiscales del cliente, importe/concepto) en lugar de un error genérico o de inventar un valor.
- **Generación de PDF real** con WeasyPrint + Jinja2 (`services/documentos_pdf.py`), motor 100% local — sin
  coste, sin llamada externa.
- **Numeración de factura segura**: `allocate_numero_factura` usa el mismo patrón de contador atómico
  (UPSERT de PostgreSQL) que los códigos `OP-`/`CLI-`, verificado bajo concurrencia.
- **Envío por email con adjuntos, gated** (`services/mailer.py`): desactivado por defecto
  (`EMAIL_SENDING_ENABLED=false`); cada envío exige además `confirmar=true` explícito en la petición. Para
  probar el envío real sin arriesgar un correo real, levanta Mailpit:
  ```bash
  docker compose --profile dev-mail up -d mailpit
  # SMTP_HOST=mailpit, SMTP_PORT=1025, SMTP_USE_TLS=false en .env
  # Buzón web: http://localhost:8025
  ```
- **Nada de esto está listo para producción sin que Judit aporte**: el texto contractual definitivo, los
  datos fiscales del emisor (`EMISOR_*`), la serie de factura (`FACTURA_SERIE`) y credenciales SMTP reales.

## API Endpoints

| Ruta | Metodo | Descripcion |
|---|---|---|
| `/api/dashboard/stats` | GET | Estadisticas del dashboard |
| `/api/sanciones` | GET | Listar sancionados (paginado, filtros) |
| `/api/sanciones/{id}` | GET | Detalle de un sancionado |
| `/api/sanciones/{id}` | PATCH | Editar estado de oportunidad, teléfono, email, web, LinkedIn y teléfono secundario |
| `/api/sanciones/{id}/seguimientos` | GET/POST | Seguimientos de un sancionado |
| `/api/sanciones/{id}/enriquecer` | POST | Enriquecimiento bajo demanda de un registro (409 si está desactivado) |
| `/api/sanciones/{id}/enriquecimiento` | GET | Historial de intentos de enriquecimiento |
| `/api/sanciones/{id}/convertir` | POST | Convertir la oportunidad en cliente (idempotente) |
| `/api/enriquecimiento/lote` | POST | Enriquecimiento en lote (doble confirmación) |
| `/api/clientes` | GET | Directorio de clientes (filtros, búsqueda) |
| `/api/clientes/{id}` | GET | Ficha completa: datos, sanciones vinculadas, deuda calculada, notas, actividad, acciones |
| `/api/clientes/{id}` | PATCH | Editar datos del cliente |
| `/api/clientes/{id}/notas` | GET/POST | Notas del cliente |
| `/api/clientes/{id}/actividad` | GET | Registro de actividad (timeline) |
| `/api/clientes/{id}/acciones` | GET/POST | Acciones agendadas |
| `/api/clientes/{id}/acciones/{accion_id}` | PATCH | Marcar acción como hecha/cancelada |
| `/api/clientes/{id}/historico/buscar` | POST | Buscar y persistir coincidencias del histórico para este cliente |
| `/api/clientes/{id}/historico` | GET | Resultados de histórico ya persistidos para este cliente |
| `/api/clientes/{id}/historico/extraer` | POST | Extracción on-demand (OpenAI, gated) sobre resultados seleccionados |
| `/api/clientes/{id}/documentos` | GET | Documentos comerciales del cliente |
| `/api/clientes/{id}/documentos/validar` | GET | Checklist de datos faltantes antes de generar (query `tipo`) |
| `/api/clientes/{id}/contrato` | POST | Generar contrato PDF (body `{precio}`) |
| `/api/clientes/{id}/factura` | POST | Generar factura PDF (body `{cuantia, concepto}`) |
| `/api/documentos-comerciales` | GET | Listar documentos comerciales (filtro `cliente_id`) |
| `/api/documentos-comerciales/{id}` | GET | Metadatos de un documento comercial |
| `/api/documentos-comerciales/{id}/pdf` | GET | Descargar el PDF |
| `/api/documentos-comerciales/{id}/enviar` | POST | Enviar por email (gated: `EMAIL_SENDING_ENABLED` + `confirmar=true`) |
| `/api/documentos-comerciales/plantillas` | GET | Listar plantillas (contrato/factura, todas las versiones) |
| `/api/documentos-comerciales/plantillas/{id}` | PATCH | Editar el HTML de una plantilla |
| `/api/documentos` | GET | Listar documentos BOE |
| `/api/documentos/{id}` | GET | Detalle de un documento |
| `/api/historico` | GET | Archivo histórico paginado (filtros `fuente`, `anio`) |
| `/api/historico/cobertura` | GET | Qué hay realmente indexado (rango y días por fuente) |
| `/api/historico/consulta` | POST | Consulta interna por CIF/DNI/matrícula/nombre, solo lectura |
| `/api/historico/backfill/plan` | POST | Previsualización del backfill (rango, volumen, token) — no toca red ni BD |
| `/api/historico/backfill` | POST | Lanzar backfill (doble puerta: flag + token de confirmación) |
| `/api/historico/backfill/runs` | GET | Progreso de los backfills lanzados (reanudables) |
| `/api/notificaciones` | GET | Listar notificaciones |
| `/api/notificaciones/unread-count` | GET | Contador de no leidas |
| `/api/notificaciones/mark-read` | POST | Marcar como leidas |
| `/api/scraping/trigger` | POST | Disparar scraping manual |
| `/api/scraping/runs` | GET | Historial de ejecuciones |
| `/api/scraping/gaps` | GET | Fechas sin ejecución completada, sin encolar scraping |

## Migraciones y operación segura

El esquema está gobernado por Alembic. `docker compose up` ejecuta primero el servicio `migrate`:

- En una base nueva aplica todas las revisiones (`0001`→`0006`).
- En una base creada por la versión previa con `create_all`, valida las tablas y columnas legadas, marca la revisión baseline y aplica las actualizaciones posteriores.
- Si la base no coincide con ese esquema, se detiene sin marcarla: haz una copia y revisa el diagnóstico antes de continuar.

No se ejecuta scraping al consultar oportunidades. La detección de huecos solo informa de fechas sin ejecución completada y puede incluir días sin publicación BOE.

## Filtros de oportunidades

`GET /api/sanciones` acepta `fecha_desde`, `fecha_hasta`, `estado_oportunidad`, `materia`, `tipo_persona`, `cuantia_min`, `cuantia_max` y `solo_con_contacto`. Sin rango explícito devuelve los últimos 30 días inclusivos.

## Pruebas

Las pruebas de backend usan fixtures/mocks y no contactan BOE, TEU, SMTP, OpenAI ni proveedores de
enriquecimiento reales. Ejecuta la batería completa con una base PostgreSQL efímera (no uses la base
de trabajo local):

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

El contenedor aplica Alembic hasta `head` y configura `TEST_DATABASE_URL_SYNC`. Sin esa variable, solo se ejecutan las pruebas puras que no necesitan PostgreSQL.

Frontend:

```bash
cd frontend
npm run typecheck   # tsc --noEmit
npm run test        # Vitest + Testing Library, jsdom
npm run lint         # ESLint (eslint-config-next + React hooks rules)
npm run build        # producción, incluye el chequeo de tipos de Next.js
```

## Fuera de la sesión 3

Quedan deliberadamente para sesiones posteriores: proveedores de enriquecimiento de pago (eInforma, Google
Places), scraping/login/extracción de LinkedIn, enriquecimiento en lote habilitado por defecto, versión cloud
multiusuario, portal externo para clientes finales, y cualquier automatización de puesta en marcha real
(backfill de 4 años completo, envío masivo de contratos/facturas) — todas estas quedan **preparadas y
probadas con fixtures**, pero su primera ejecución real requiere que Judit aporte datos (ver
`docs/GUIA_OPERATIVA.md`) y confirme explícitamente cada acción.

## Estructura del proyecto

```
boe-sanciones/
  docker-compose.yml
  docker-compose.test.yml
  .env.example
  docs/
    GUIA_OPERATIVA.md   # Puesta en marcha real, backfill, documentos, envío
    LIMITES.md          # RGPD, límite TEU 90 días, coste OpenAI, variabilidad documental
  backend/
    app/
      main.py            # FastAPI app (todos los routers, sin create_all)
      config.py           # Settings (todas las puertas de coste/terceros, off por defecto)
      database.py         # SQLAlchemy (async + sync)
      celery_app.py       # Celery config — backfill/extracción histórica NUNCA en beat
      models/             # ORM models: cliente, historico, documentos_comerciales, enriquecimiento...
      schemas/             # Pydantic schemas, uno por dominio
      api/                # REST endpoints: sanciones, clientes, historico, documentos_comerciales...
      services/           # Business logic
        boe_client.py     # BOE API client
        classifier.py     # Rule-based classifier
        parser.py         # XML/HTML/PDF parser
        extractor.py      # OpenAI extraction
        notifier.py       # Email digest (usa mailer.py)
        mailer.py         # SMTP con adjuntos, gated
        clientes.py       # Conversión idempotente, código CLI, deuda calculada
        documentos_pdf.py         # Render HTML→PDF (WeasyPrint + Jinja2)
        documentos_comerciales.py # Validación, numeración de factura, generación
        enrichment/        # Cascada de enriquecimiento (sesión 2)
          base.py, service.py, patterns.py, verify.py, providers/
        historico/          # Histórico de hasta 4 años (sesión 3)
          patterns.py        # Regex DNI/NIE/CIF/matrícula, sin LLM
          indexado.py         # Upsert idempotente en historico_docs
          busqueda.py          # Búsqueda exacta (JSONB/GIN) + FTS por nombre
          teu_publico.py        # Conector TEU opcional, off por defecto
      tasks/               # Celery tasks
        scraping.py           # Pipeline diario + acumulación histórica gratuita
        enrichment.py          # Enriquecimiento bajo demanda/lote
        historico_backfill.py   # Backfill manual, doble puerta, reanudable
        historico_extraccion.py  # Extracción OpenAI on-demand sobre histórico
    alembic/versions/     # 0001..0006, cadena lineal
    tests/                # pytest, sin red/OpenAI/SMTP reales
  frontend/
    src/app/              # Next.js pages: /, sanciones/, clientes/, historial/, consulta/, scraping/...
    src/components/ui/    # Sistema de diseño "Minimalismo Autoritario"
    src/lib/              # API client, types, formatters
    vitest.config.ts      # Vitest + Testing Library + jsdom
```
