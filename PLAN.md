# PLAN.md — Sistema de captación y gestión de sanciones del BOE (MVP local)

> Documento maestro de desarrollo. Sirve de guía única para llevar el MVP descrito en
> `Propuesta_tecnica_economica_boe_sanciones.docx` hasta un estado **completo y entregable**.
> Está pensado para iterarse con un AI Coding Agent: cada fase contiene tareas accionables
> con criterios de verificación.

---

## 0. Resumen ejecutivo

Herramienta **web de uso interno y local** para que la clienta (Judit, abogada) transforme las
sanciones publicadas en el **BOE** (incluyendo el **Tablón Edictal Único / TEU** de la DGT) en una
operativa comercial ordenada:

1. **Captar** automáticamente las sanciones de **los últimos 30 días** (potenciales clientes).
2. **Enriquecer** automáticamente cada caso con **teléfono / email** (lo más valioso para Judit).
3. **Gestionar** oportunidades (filtrar, priorizar, seguimiento comercial, descartar).
4. **Convertir** una oportunidad en **cliente**, con su **ficha**, notas, registro de actividad y acciones.
5. **Enviar** desde la ficha el **contrato** (PDF autogenerado: igual para todos salvo CIF y precio) y la
   **factura** (PDF autogenerado con cuantía y concepto), por **email con adjuntos**.
6. **Consultar el histórico sancionador de 4 años SOLO de un cliente concreto**, buscando por
   DNI/CIF/nombre/matrícula en un índice propio + buscador público del TEU, y extrayendo de forma
   estructurada (OpenAI) **solo** los documentos que interesen.

Lo que **NO** entra en este MVP: nube/acceso remoto, portal público para clientes finales, alta de pago
("Alta 50€"), multiusuario avanzado. Quedan como evolutivos posteriores.

---

## 1. Alcance confirmado con cliente (decisiones cerradas)

Estas decisiones se han validado y son **vinculantes** para el desarrollo:

| Tema | Decisión |
| --- | --- |
| **Tipo de producto** | Solo herramienta **interna**, monousuario, en **local**. Los mockups de portal público / "Alta 50€" / consulta ciudadana son ideas de fases futuras → **fuera del MVP**. |
| **Dominio de sanciones** | **Todas** las materias del BOE (tráfico/DGT, seguridad social, sanidad, transporte, etc.). |
| **Fuente DGT/TEU** | **Ambos** usos: captación diaria del TEU + consulta histórica bajo demanda por DNI/CIF/matrícula. |
| **Autenticación** | **Sin login** (uso local monousuario). |
| **Teléfono/email** | **Extracción automática** desde Internet (sin LLM o el mínimo posible), con **entrada manual** como respaldo de emergencia. Es la funcionalidad **más crítica** del proyecto. |
| **Histórico 4 años** | **Solo para clientes**, bajo demanda. **Sin** extracción estructurada masiva del histórico; estructurada **solo** sobre últimos 30 días + documentos que casan con un cliente. Diseño: **índice propio ligero + buscador público TEU** (enfoque combinado). |
| **Extracción estructurada (OpenAI)** | Solo sobre el **bloque de últimos 30 días** y, **bajo demanda**, sobre documentos del histórico que casan con un cliente. |
| **Contrato por email** | El sistema **genera el PDF** del contrato a partir de una **plantilla** (rellena CIF y precio) y lo envía. La plantilla la aportará/definirá la clienta. |
| **Factura por email** | El sistema **genera el PDF** de la factura (cuantía, concepto, datos fiscales) y lo envía. |
| **Enriquecimiento – presupuesto** | Empezar con **fuentes gratuitas**; dejar las de pago (eInforma, etc.) como **integración configurable** activable cuando Judit quiera. |
| **Enriquecimiento – alcance** | **Configurable**: por defecto **bajo demanda**, con opción de lanzar en **lote** sobre el bloque reciente. |

---

## 2. Hallazgos técnicos clave (investigación) que condicionan el diseño

> Verificados con fuentes oficiales (BOE OpenData, LOPDGDD, sede DGT/TEU). Importante leerlos antes de
> implementar el histórico y el enriquecimiento.

### 2.1. Identificadores en el BOE: cómo casar a una persona

- **Notificaciones del TEU** (art. 44 Ley 39/2015 — donde caen las **multas de la DGT**): por la
  **Disp. Adic. 7ª LOPDGDD** se identifica al afectado por el **número COMPLETO de DNI/NIE/CIF, SIN
  nombre y apellidos**. → En TEU **se puede casar por DNI/CIF exacto** (y por matrícula).
- **Sanciones ordinarias del BOE** (resoluciones, sección III/V no-anuncio): se identifica por
  **nombre y apellidos + 4 cifras aleatorias** del DNI (`***4567**`). → Aquí **no hay DNI completo**;
  se casa por **nombre (+ 4 dígitos visibles)**.
- **Consecuencia de diseño**: la búsqueda del histórico de un cliente debe combinar **DNI/CIF/matrícula
  exactos** (para TEU) **y** **nombre/razón social normalizado** (para BOE ordinario). Un cliente
  guarda **todas** sus claves (CIF, DNI, nombre, matrículas conocidas).

### 2.2. Disponibilidad y APIs

- **API de sumarios BOE** (oficial, gratis, GET): `https://boe.es/datosabiertos/api/boe/sumario/{AAAAMMDD}`
  (JSON o XML por cabecera `Accept`). Da, por día, todos los documentos con URLs PDF/XML/HTML. Sumarios
  disponibles **desde 1960**. **Ya está integrado** en `backend/app/services/boe_client.py`.
- **No existe API por NIF** del BOE/TEU. El **buscador del TEU** es un **formulario web** (scraping):
  busca por texto (NIF, NIE, matrícula, nombre), Administración, materia, fecha, nº BOE.
- **Caducidad del TEU**: las notificaciones del TEU solo son **libremente accesibles 3 meses**; pasado
  ese plazo se necesita el **código de verificación (CSV)** del anuncio. → El **histórico profundo del
  TEU anterior a 3 meses NO es recuperable** públicamente.
- **BOE ordinario**: el contenido (PDF/XML/HTML) **permanece accesible** indefinidamente.

### 2.3. Estrategia de histórico resultante (combinada e "inteligente")

Como Judit solo quiere el histórico **de sus clientes**, evitamos extracción masiva y minimizamos coste:

1. **Backfill ligero, sin LLM** (tarea inicial, una vez): recorrer sumarios del BOE de los últimos
   **N años** (config, objetivo 4), filtrar **solo candidatos a sanción** con el **clasificador por
   reglas ya existente** (`classifier.py`, gratis), y extraer por **regex** los **identificadores**
   (DNI/NIE/CIF, matrículas) + **nombres** + fecha + URL del documento. Guardar en un **índice compacto**
   (`historico_indice`) con **Full-Text Search de Postgres**. **Nada de OpenAI** aquí.
2. **Acumulación diaria**: el scraping diario añade al índice (cubre TEU dentro de su ventana de 3 meses).
3. **Búsqueda por cliente (al convertir / bajo demanda)**: consultar el índice por DNI/CIF/matrícula
   (exacto) + nombre (FTS) → lista de documentos candidatos. Complementar con **scraping del buscador
   público del TEU** en vivo (ventana 3 meses).
4. **Extracción estructurada on-demand**: solo sobre los documentos del histórico que el usuario marque
   como de interés (OpenAI), para completar la ficha del cliente.

**Limitación a comunicar a la clienta** (riesgo R-1): el histórico **TEU/DGT** anterior a 3 meses solo
estará disponible para lo que **hayamos acumulado** desde la puesta en marcha; el BOE ordinario sí cubre 4 años.

---

## 3. Estado actual del repositorio (qué se reutiliza)

### 3.1. Ya implementado y reutilizable (NO rehacer)

**Backend (`backend/`)** — FastAPI + Celery + SQLAlchemy 2.0 + Postgres + Redis:

- `services/boe_client.py`: descarga de sumario (API JSON), aplanado, descarga de contenido HTML/XML/PDF, hash. ✅
- `services/classifier.py`: clasificación por reglas (título + verificación de cuerpo). ✅ **Reutilizar en backfill.**
- `services/parser.py`: `xml_to_text`, `html_to_text`, `pdf_to_text`, orquestación. ✅
- `services/extractor.py`: extracción estructurada con OpenAI (`client.beta.chat.completions.parse`, schema `ResultadoExtraccion`/`AfectadoExtraido`). ✅ **Reutilizar para 30 días + on-demand.**
- `services/teu_client.py`: scraping del índice TEU diario + PDFs. ✅ **Ampliar para captación + buscador por NIF.**
- `services/notifier.py`: notificación in-app + email digest (SMTP). ✅ **Reutilizar y ampliar a envío de contrato/factura.**
- `tasks/scraping.py`: pipeline diario (`run_daily_scraping`), idempotencia por `ScrapingRun`/`boe_id`. ✅ **Refactor a "últimos 30 días" + colas nuevas.**
- `celery_app.py`: beat 07:30 y 19:30 Europe/Madrid. ✅
- `api/` (dashboard, sanciones, documentos, scraping, notificaciones), `database.py` (async + sync), `main.py` (lifespan crea tablas), Alembic configurado. ✅

**Frontend (`frontend/`)** — Next.js 16 + React 19 + Tailwind v4:

- Páginas: `/` (dashboard), `/sanciones`, `/sanciones/[id]`, `/notificaciones`, `/scraping`. ✅ funcionales.
- `src/lib/api.ts`, `types.ts`, `utils.ts`. ✅
- **A rediseñar** al sistema visual "BOE Oportunidades / Minimalismo Autoritario" (ver §8).

**Infra**: `docker-compose.yml` (postgres:16, redis:7, backend, celery-worker, celery-beat, frontend). ✅

**Scripts/docs**: `boe.py` (prototipo Streamlit standalone — **legacy, no tocar / candidato a archivar**),
`boe_sancionadores_2026.md` (guía de reglas de detección — referencia), `indicaciones_basicas.md`, `README.md`.

### 3.2. Modelo de datos actual

- `BoeDocumento` (`models/documento.py`): documento BOE crudo (boe_id, fecha, sección, título, `texto_plano`, `familia_sancionadora`, urls, `raw_sumario_item`, `source`). 1—N con `Sancionado`.
- `Sancionado` (`models/sancionado.py`): registro extraído (nombre, tipo_persona, identificador, tipo_identificador, dirección, **telefono**, **email**, matricula_coche, importe_multa_eur, tipo_infraccion, razon_sancion, expediente, estado_publicacion, plazos, base_legal, organismo_emisor, dominio_material).
- `Seguimiento` (nota + estado por sancionado), `Notificacion` (alertas in-app), `ScrapingRun` (ejecuciones).

### 3.3. GAP principal frente a la propuesta (lo que falta)

- Modelo de dominio **Oportunidad → conversión → Cliente** (hoy solo existe `Sancionado`).
- **Cliente** con **ficha**: datos fiscales, persona de contacto, **deuda pendiente**, notas, **registro de
  actividad** (timeline), **acciones** (agendar llamadas).
- **ID/código único visible** para oportunidad y cliente (requisito explícito de la clienta).
- **Enriquecimiento automático de contacto** (teléfono/email) — no existe.
- **Histórico de 4 años por cliente** (índice + búsqueda + extracción on-demand) — no existe.
- **Generación y envío de contrato/factura en PDF** por email con adjuntos — no existe.
- **Filtros** de la propuesta (fecha de contrato, fecha última sanción, persona física/jurídica, cuantía,
  estado de oportunidad) — parciales.
- **Backfill histórico** + tareas Celery asociadas — no existen.
- **Rediseño visual** completo y pantallas nuevas (panel de multas, lista de clientes, ficha, histórico, consulta).

---

## 4. Arquitectura objetivo

```
┌──────────────────────── Frontend Next.js (local :3000) ────────────────────────┐
│  Inicio · Panel de Multas (oportunidades 30d) · Clientes · Ficha · Historial    │
│  · Consulta por DNI/CIF · Scraping/Operación · Notificaciones · Ajustes         │
└───────────────────────────────────┬─────────────────────────────────────────────┘
                                     │ REST (NEXT_PUBLIC_API_URL)
┌───────────────────────────────────▼─────────────────────────────────────────────┐
│  Backend FastAPI (:8000)   +   Celery worker/beat   +   Postgres   +   Redis      │
│                                                                                   │
│  Pipelines:                                                                       │
│   (P1) Ingesta diaria 30d  → clasificar → extraer (OpenAI) → Sancion/Oportunidad  │
│   (P2) Enriquecimiento contacto (cascada de proveedores, regex, manual fallback)  │
│   (P3) Backfill + índice histórico 4 años (regex, sin LLM) + búsqueda por cliente │
│   (P4) Conversión a Cliente + extracción on-demand del histórico                  │
│   (P5) Documentos: generar PDF contrato/factura + envío email con adjuntos        │
└───────────────────────────────────────────────────────────────────────────────────┘
        │ APIs externas: BOE OpenData (sumario), BOE/TEU (web), OpenAI,
        │ proveedores de enriquecimiento (búsqueda web / Places / eInforma opc.), SMTP
```

---

## 5. Modelo de dominio objetivo (esquema de BD)

> Estrategia: **reutilizar** `BoeDocumento` y `Sancionado` como base; **añadir** entidades nuevas.
> `Sancionado` representa la **sanción extraída** (= "oportunidad" mientras no sea cliente). Se le añade
> estado de oportunidad, código visible y campos de contacto enriquecido. Se introduce `Cliente` y las
> entidades de CRM, histórico y documentos.
> Crear **migración Alembic** por cada cambio de modelo (ver §11).

### 5.1. `Sancionado` (ampliar) — la "oportunidad"/sanción

Añadir campos:
- `codigo: str` — **ID único visible** (p.ej. `OP-2026-000123`). Indexado, único.
- `estado_oportunidad: str` — enum: `nueva` · `revisada` · `contactada` · `descartada` · `cliente`. Default `nueva`.
- `materia / tipo_multa: str` — materia normalizada (Tráfico, Seguridad Social, Sanidad…).
- `localidad`, `provincia`, `codigo_postal` — **persistir** (hoy el extractor los devuelve pero no se guardan).
- `tipo_procedimiento`, `importe_deuda_eur`, `plazo_pago_voluntario`, `fecha_resolucion`, `observaciones` — **persistir** (el extractor ya los produce).
- `fecha_infraccion: date`, `lugar_infraccion: str`, `articulo_infringido: str`, `numero_expediente: str` — campos pedidos en los comentarios del docx (mapear desde extractor; ampliar schema si falta).
- `es_apremio_embargo: bool` / `tipo_acto: str` — para distinguir providencias de apremio / embargos.
- **Contacto enriquecido**: `contacto_estado: str` (`pendiente`·`encontrado`·`no_encontrado`·`manual`), `contacto_fuente: str`, `contacto_confidence: float`, `contacto_actualizado_at`, `telefono_secundario`, `web`. (`telefono`/`email` ya existen.)
- `cliente_id: FK→clientes.id (nullable)` — set al convertir.

### 5.2. `Cliente` (nuevo)

- `id`, `codigo: str` (**ID único visible**, p.ej. `CLI-2026-0042`), `created_at`, `updated_at`.
- Identidad: `nombre_razon_social`, `tipo_persona` (`fisica`/`juridica`), `cif_nif`, `dni_nie`, `matriculas: JSONB` (lista de claves para búsqueda histórica).
- Contacto: `persona_contacto`, `telefono`, `email`, `direccion_fiscal`, `localidad`, `provincia`, `codigo_postal`, `web`, `sector`.
- Comercial: `estado_cliente` (`activo`/`inactivo`), `fecha_contrato: date`, `precio_contrato: numeric`, `deuda_pendiente_eur: numeric` (calculada o manual).
- `sancion_origen_id: FK→sancionados.id` — la oportunidad que originó el cliente.
- Relaciones: `sanciones` (1—N `Sancionado`), `notas`, `actividades`, `acciones`, `documentos` (contratos/facturas), `historico_resultados`.

### 5.3. CRM de cliente

- `NotaCliente`: `id`, `cliente_id`, `texto`, `autor`, `created_at`. (Notas del cliente — mockup ficha.)
- `ActividadCliente` (timeline "Registro de actividad"): `id`, `cliente_id`, `tipo` (`llamada`·`email`·`pago`·`nota`·`conversion`·`sistema`), `titulo`, `detalle`, `metadata: JSONB`, `created_at`.
- `AccionAgendada` (agendar llamadas — "Acciones"): `id`, `cliente_id`, `tipo` (`llamada`·`email`·`tarea`), `titulo`, `fecha_programada: datetime`, `estado` (`pendiente`·`hecha`·`cancelada`), `notas`.
- `Seguimiento` (existente): mantener para seguimiento de oportunidades; al convertir, registrar `ActividadCliente`.

### 5.4. Histórico 4 años

- `HistoricoDoc` (índice ligero del backfill/acumulación): `id`, `boe_id`, `fecha_publicacion`, `fuente` (`boe`/`teu`), `seccion`, `url_pdf/html/xml`, `texto_plano` (opcional/compactado), `identificadores: JSONB` (lista DNI/NIE/CIF), `matriculas: JSONB`, `nombres: JSONB`, `tsv` (columna `tsvector` para FTS). Índices: GIN sobre `tsv` y sobre `identificadores`/`matriculas`.
- `HistoricoResultado` (match cliente ↔ documento histórico): `id`, `cliente_id`, `historico_doc_id` (o `boe_id`), `score`, `via_match` (`dni`·`cif`·`matricula`·`nombre`·`teu_publico`), `extraido: bool`, `datos_extraidos: JSONB` (al hacer extracción on-demand), `created_at`.

### 5.5. Documentos comerciales

- `PlantillaContrato` (config; puede ser 1 fila singleton o por tipo): `id`, `nombre`, `contenido` (HTML/markdown con placeholders `{{cif}}`, `{{precio}}`, `{{razon_social}}`…), `version`, `activo`.
- `DocumentoComercial`: `id`, `cliente_id`, `tipo` (`contrato`/`factura`), `numero` (correlativo de factura), `pdf_path`, `datos: JSONB` (cif, precio, cuantía, concepto…), `enviado: bool`, `email_destino`, `enviado_at`, `created_at`.
- `AdjuntoEmail` (opcional) o `metadata` en `DocumentoComercial`/`ActividadCliente` para registrar adjuntos.

### 5.6. Config / operación

- `ScrapingRun` (existente): ampliar `tipo` (`diario_30d`·`backfill`·`enriquecimiento`·`historico_cliente`).
- `AppConfig` o variables `.env` (ver §12) para: API keys de enriquecimiento, SMTP, datos del emisor de facturas, plantilla de contrato, modo de enriquecimiento (auto/bajo demanda), profundidad de backfill.

---

## 6. Backend — pipelines y servicios (detalle de implementación)

### P1 · Ingesta diaria del bloque de 30 días + extracción estructurada

- Refactor de `tasks/scraping.py`:
  - Mantener `run_daily_scraping(fecha)` para el día actual (beat 07:30/19:30).
  - El **panel de oportunidades** trabaja sobre **"últimos 30 días"** ⇒ vista/consulta por rango, no
    re-scrapeo. Garantizar que la ingesta diaria cubre huecos (si faltan días, encolar su scraping).
  - Tras crear `Sancionado`, asignar `codigo` único y `estado_oportunidad="nueva"`, y (según config)
    **encolar enriquecimiento** (P2) — ver §1 (por defecto bajo demanda; lote opcional).
- Persistir **todos** los campos del extractor (corrige el gap actual: localidad/provincia/CP/
  tipo_procedimiento/importe_deuda/plazo_pago/fecha_resolucion/observaciones) y los nuevos (fecha_infracción,
  lugar, artículo, nº expediente, apremio/embargo). Ampliar `AfectadoExtraido` si algún campo no existe.
- TEU como fuente de captación: consolidar `_scrape_teu` para que también alimente oportunidades del día.

**Verificación P1**: ejecutar trigger manual para una fecha conocida con sanciones → aparecen `Sancionado`
con `codigo`, `estado_oportunidad`, materia y campos completos; visibles en `/api/sanciones?fecha_desde=...`.

### P2 · Enriquecimiento de contacto (teléfono/email) — **MÓDULO CRÍTICO**

Servicio nuevo `services/enrichment.py` con **cascada de proveedores** (interfaz `ContactProvider`),
**barato y sin LLM** (o mínimo). Orden por defecto:

1. **Empresas (CIF/razón social)**:
   - `OpenMercantil`/BORME (gratis): domicilio, web, estado (rara vez teléfono).
   - **Google Places / Maps** (Place Details → `formatted_phone_number`, `website`): buscar por
     razón social + localidad/provincia. (free tier / configurable.)
   - Scraping de la **web corporativa** encontrada → regex de teléfono/email.
   - (Opcional, configurable, de pago) **eInforma API** por CIF → teléfono, email, web. **Desactivada por defecto.**
2. **Particulares (DNI/nombre)** y fallback general:
   - **API de búsqueda web** (configurable: SerpAPI / Bing / Google CSE) con query
     `"{nombre}" {localidad/provincia} teléfono|contacto` → top-N URLs.
   - **Scraping** de esas páginas → **regex** de teléfono español (`(?:\+34|0034)?[\s.-]?[6-9]\d{2}...`) y email.
   - (Opcional) mini-paso LLM **solo** para **desambiguar** cuál de los candidatos corresponde (activable;
     prompt mínimo y barato). Por defecto **desactivado**.
3. **Respaldo manual** siempre: la UI permite introducir/editar teléfono y email a mano (estado `manual`).

Características obligatorias:
- **Caché** de resultados por identificador (evitar repetir y controlar coste).
- **Trazabilidad**: guardar `contacto_fuente`, `contacto_confidence`, URL de origen, timestamp.
- **Rate limiting** y **timeouts**; reintentos con `tenacity`.
- **Config**: `ENRICHMENT_MODE` (`on_demand`/`batch`), proveedores activos vía `.env` (ver §12).
- **Aviso RGPD** (ver §9): registrar base de licitud; el dato de contacto de particulares es sensible.

Tarea Celery `enrich_contact(sancionado_id)` y `enrich_batch(rango)`. Endpoint para lanzar/relanzar.

**Verificación P2**: para una empresa con web pública, el sistema rellena teléfono/email automáticamente
con fuente y confianza; para un caso sin datos, queda `contacto_estado="no_encontrado"` y editable a mano.
Medir **tasa de acierto** sobre una muestra real (criterio de aceptación con la clienta).

### P3 · Histórico de 4 años: índice + búsqueda

- **Backfill** (`tasks/backfill.py`, `build_historico_index(desde, hasta)`):
  - Iterar días con `boe_client.fetch_sumario` (reutiliza retries). Para cada doc candidato (filtro
    `classifier` por título + sección, **sin** verificación pesada si se prioriza velocidad), descargar
    texto (`parser`), **regex** de identificadores/matrículas/nombres, insertar en `HistoricoDoc` con `tsv`.
  - **Sin OpenAI**. Idempotente por `boe_id`. Progreso en `ScrapingRun(tipo="backfill")`.
  - Config de profundidad `HISTORICO_BACKFILL_YEARS` (objetivo 4). Ejecutable por lotes/reanudable.
- **Acumulación diaria**: el pipeline P1 inserta también en `HistoricoDoc` (cubre TEU dentro de 3 meses).
- **Búsqueda por cliente** (`services/historico.py`, `buscar_historico(cliente)`):
  - Match exacto por `cif_nif`/`dni_nie`/`matriculas` sobre `identificadores`/`matriculas` (JSONB/GIN).
  - Match por nombre con **FTS** (`tsv @@ plainto_tsquery`) + normalización (mayúsculas/acentos) y, si hay
    4 dígitos del DNI visibles, filtrar.
  - **Complemento en vivo**: `teu_client.buscar_teu_por_nif(nif)` scrapeando el formulario público
    (ventana 3 meses) y fusionando resultados (marcando `via_match="teu_publico"`).
  - Devolver `HistoricoResultado` con info parcial (fecha, fuente, título, enlace) **sin** extraer.
- **Extracción on-demand** (`extraer_historico(historico_resultado_ids)`): correr `extractor` (OpenAI)
  **solo** sobre los seleccionados; guardar `datos_extraidos`, marcar `extraido=true`, registrar actividad.

**Verificación P3**: con el índice poblado, buscar por un CIF/nombre de prueba devuelve sus documentos;
extraer uno rellena sus campos estructurados. Confirmar límite TEU (R-1) documentado en la UI.

### P4 · Conversión de oportunidad en cliente

- Endpoint `POST /api/sanciones/{id}/convertir` → crea `Cliente` (con `codigo`, datos copiados de la
  sanción + contacto enriquecido), set `Sancionado.cliente_id` y `estado_oportunidad="cliente"`,
  registra `ActividadCliente(tipo="conversion")`. Idempotente (si ya es cliente, no duplica).
- Tras convertir, ofrecer lanzar **búsqueda histórica** (P3) para ese cliente.

**Verificación P4**: convertir una oportunidad la mueve a Clientes con ID visible y deja traza en el timeline.

### P5 · Documentos comerciales (contrato + factura) y envío por email

- `services/documentos_pdf.py`: render de **plantilla → PDF**.
  - **Contrato**: plantilla (`PlantillaContrato`) con placeholders; rellenar `{{cif}}`, `{{precio}}`,
    `{{razon_social}}`, `{{fecha}}`… → PDF. (Motor sugerido: HTML+CSS → PDF con WeasyPrint, o Jinja2+plantilla.)
  - **Factura**: generar PDF con **datos del emisor** (config), datos fiscales del cliente, **cuantía**,
    **concepto**, **número correlativo** de factura, fecha, IVA.
- `services/notifier.py` (ampliar) o `services/mailer.py`: envío SMTP con **adjuntos** (contrato/factura +
  adjuntos manuales). Reutiliza credenciales SMTP de `.env`.
- Endpoints (ver §7): `POST /api/clientes/{id}/contrato` (genera+envía), `POST /api/clientes/{id}/factura`.
- Registrar `DocumentoComercial` + `ActividadCliente(tipo="email")` con resultado del envío.

**Verificación P5**: desde la ficha, enviar contrato genera un PDF con el CIF/precio correctos y llega por
email con adjunto; enviar factura genera PDF con cuantía/concepto/numeración y se registra en el timeline.

---

## 7. API (endpoints) — nuevos y cambios

Mantener routers existentes; añadir/ajustar:

**Oportunidades / sanciones** (`/api/sanciones`):
- `GET /` — añadir filtros: `estado_oportunidad`, `materia`, `persona` (fisica/juridica), `cuantia_min/max`,
  `fecha_pub_desde/hasta`, `fecha_infraccion_*`, `solo_con_contacto`. Rango por defecto: **últimos 30 días**.
- `GET /{id}` — incluir contacto enriquecido y `codigo`.
- `POST /{id}/enriquecer` — lanza P2 para ese registro.
- `PATCH /{id}` — editar contacto manual / estado_oportunidad.
- `POST /{id}/convertir` — P4.

**Clientes** (`/api/clientes`, nuevo router):
- `GET /` — directorio (filtros: Todos/Activos/Inactivos/Con multas pendientes/Sector; búsqueda). Export CSV.
- `POST /` — alta manual de cliente (botón "Nuevo Cliente").
- `GET /{id}` — ficha completa (datos, contacto, deuda, sanciones, notas, actividad, acciones).
- `PATCH /{id}` — editar.
- `POST /{id}/notas`, `GET /{id}/notas`.
- `POST /{id}/acciones` (agendar), `GET /{id}/acciones`, `PATCH /{id}/acciones/{aid}`.
- `GET /{id}/actividad` — timeline.
- `POST /{id}/historico/buscar` — P3 (búsqueda). `POST /{id}/historico/extraer` — P3 (on-demand).
- `GET /{id}/historico` — resultados.
- `POST /{id}/contrato`, `POST /{id}/factura` — P5 (body con precio / cuantía+concepto + adjuntos).

**Histórico / consulta** (`/api/historico` o `/api/consulta`):
- `POST /consulta` — búsqueda por DNI/CIF/matrícula/nombre (pantalla "Consulta por DNI/CIF", uso interno).
- `GET /` — listado del archivo histórico con estado de prescripción (pantalla "Historial").

**Operación** (`/api/scraping`):
- `POST /backfill` — lanza P3 backfill (rango/años). `GET /runs` (incluye tipo).
- `POST /enriquecimiento/lote` — P2 en lote sobre rango.

**Dashboard** (`/api/dashboard/stats`): añadir métricas del panel (nuevas, revisadas, **tasa de conversión**).

Actualizar `frontend/src/lib/api.ts` y `types.ts` con todo lo anterior.

---

## 8. Frontend — pantallas y diseño

### 8.1. Sistema de diseño (obligatorio)

Adoptar el sistema **"Minimalismo Autoritario / Claridad Soberana"** definido en
`stitch_historial_de_multas/criterio_administrativo/DESIGN.md`:
- Paleta: `primary #002045`, `surface #f7fafc`, capas tonales sin bordes 1px; CTAs con degradado 135°
  `#002045→#1a365d`; tipografía **Inter**; chips de estado (Pendiente/Pagado/Ejecutiva/Anulado);
  sin divisores horizontales (espaciado + hover); iconografía lineal 1.5px.
- Implementar tokens en Tailwind v4 (`globals.css`) y componentes base (Botón, Card, Tabla, Chip, Input, Sidebar).
- Marca: **"BOE Oportunidades"** / sidebar "BOE Gestión".

> Los `code.html` de cada carpeta de `stitch_historial_de_multas/` son la **referencia visual** de cada
> pantalla (úsalos como guía de maquetación, adaptados a React/Tailwind).

### 8.2. Pantallas (mapeo a mockups y rutas)

| Pantalla | Ruta | Referencia (mockup) | Contenido clave |
| --- | --- | --- | --- |
| **Inicio** | `/` | `media/image.png`, `inicio_acceso_directo_corregido` (solo estética) | Acceso directo a Panel de Multas, Historial, Clientes. Métricas resumen. |
| **Panel de Multas** (oportunidades) | `/oportunidades` (o `/sanciones`) | `media/image2.png`, `panel_de_multas` | "Multas del Día/Semana/Mes", tarjetas (Nuevas/Revisadas/**Conversión**), filtros (búsqueda, fecha, estado, materia, persona, cuantía), tabla con **CIF/NIF, tipo de multa, fecha, estado, teléfono, acciones**, botón **Convertir en Cliente**, **ID visible**. |
| **Clientes (Directorio)** | `/clientes` | `media/image3.png`, `lista_de_clientes` | Tabla razón social, CIF/NIF, teléfono, última multa, estado; filtros Todos/Activos/Inactivos/Con multas pendientes/Sector; **Exportar**, **Nuevo Cliente**, "Ver Ficha". |
| **Ficha de Cliente** | `/clientes/[id]` | `media/image2.jpg`, `ficha_de_cliente` | Cabecera (razón social, CIF, estado, **deuda pendiente**), Información de contacto, **Historial de sanciones**, **Notas del cliente** (+ añadir), **Registro de actividad** (timeline), **Acciones**: Editar, Nueva Multa, **Agendar llamada**, **Enviar contrato**, **Enviar factura**, **ID visible**. |
| **Historial de sanciones** | `/historial` | `media/image4.png`, `historial_de_multas` | Archivo histórico, totales (expedientes, importe acumulado, pendiente de pago), filtros año/estado, **estado de prescripción/vigencia** (chips URGENTE/PRÓXIMO/RECIENTE/ARCHIVADO). |
| **Consulta por DNI/CIF** | `/consulta` | `consulta_por_dni_cif` | **Uso interno**: introducir DNI/CIF/matrícula → resultados del índice + TEU público (histórico bajo demanda). |
| **Detalle de sanción** | `/sanciones/[id]` | (existente) | Datos extraídos, enlace al **documento original del BOE** (PDF/HTML), contacto, seguimiento. |
| **Operación / Scraping** | `/operacion` | (existente `/scraping`) | Trigger manual, **lanzar backfill histórico**, lanzar enriquecimiento en lote, ver `ScrapingRun`. |
| **Notificaciones** | `/notificaciones` | (existente) | Alertas + badge de no leídas en sidebar. |

Requisitos transversales:
- **Acceso al documento original del BOE** desde sanción/histórico (abrir PDF/HTML oficial).
- **Estado temporal/prescripción** visible donde aplique.
- Edición manual de contacto en oportunidad y ficha.
- Indicadores de **fuente/confianza** del contacto.

**Verificación §8**: navegación completa entre pantallas, datos reales del backend, diseño alineado al sistema.

---

## 9. Seguridad, privacidad y cumplimiento (MVP local)

- **Sin login** (uso local monousuario). Gestión adecuada de **credenciales** (API keys, SMTP) vía `.env`
  fuera del control de versiones (`.gitignore` ya cubre `.env`).
- Datos en **Postgres local**; no exposición a Internet.
- **RGPD / enriquecimiento (importante)**: la obtención automática de teléfono/email de **particulares**
  trata datos personales. Documentar **base de licitud** (interés legítimo / actividad profesional de la
  abogada), minimización, y permitir **borrado/edición**. Guardar **fuente y fecha** de cada dato. La
  **valoración jurídica final corresponde a la clienta** (es abogada) — dejar constancia en el README/onboarding.
- Preparar el diseño para una futura capa cloud/multiusuario **sin** implementarla ahora.

---

## 10. Plan de fases y tareas accionables (checklist para iterar con el AI Agent)

> Cada tarea es independiente y verificable. Marca `[x]` al completar. Crear migración Alembic con cada
> cambio de modelo. Trabajar fase a fase.

### Fase 0 — Cierre funcional y fundamentos (preparación)
- [ ] Confirmar con la clienta: plantilla de contrato, datos del emisor de facturas, numeración de facturas, lista de materias/tipos de multa relevantes, muestra real para medir tasa de acierto de contacto.
- [ ] Definir enums y `codigo` (formatos `OP-YYYY-NNNNNN`, `CLI-YYYY-NNNN`, `FAC-YYYY-NNNN`).
- [ ] Configurar Alembic operativo (primera revisión = estado actual) y desactivar `create_all` en `lifespan` cuando Alembic gobierne el esquema (o mantener ambos coherentes en local).

### Fase 1 — Modelo de dominio y migraciones
- [ ] Ampliar `Sancionado` (§5.1) + migración. → verify: campos en BD y en `/api/sanciones/{id}`.
- [ ] Crear `Cliente`, `NotaCliente`, `ActividadCliente`, `AccionAgendada` (§5.2/5.3) + migración.
- [ ] Crear `HistoricoDoc` (con `tsvector` + GIN) y `HistoricoResultado` (§5.4) + migración.
- [ ] Crear `PlantillaContrato`, `DocumentoComercial` (§5.5) + migración.
- [ ] Schemas Pydantic para todas las entidades nuevas.

### Fase 2 — Ingesta 30 días + persistencia completa (P1)
- [ ] Persistir todos los campos del extractor + nuevos (fecha_infracción, lugar, artículo, nº expediente, apremio/embargo). Ampliar `AfectadoExtraido` si falta. → verify: doc real rellena todos los campos.
- [ ] Asignar `codigo` y `estado_oportunidad` al crear `Sancionado`.
- [ ] Vista/consulta "últimos 30 días" + filtros nuevos en `/api/sanciones`.
- [ ] Consolidar captación TEU diaria en el flujo de oportunidades.

### Fase 3 — Enriquecimiento de contacto (P2) — **prioridad alta**
- [ ] `services/enrichment.py` con interfaz `ContactProvider` + cascada (Places/web-search/scraping+regex; eInforma opcional).
- [ ] Regex robustas de teléfono/email español; caché; trazabilidad (fuente/confianza/URL).
- [ ] Tareas Celery `enrich_contact` / `enrich_batch`; endpoints `POST /sanciones/{id}/enriquecer` y lote.
- [ ] Edición manual de contacto (PATCH) + UI.
- [ ] **Medir tasa de acierto** sobre muestra real → criterio de aceptación con la clienta.

### Fase 4 — Clientes, ficha y CRM (P4 + UI)
- [ ] Router `/api/clientes` (CRUD, notas, acciones, actividad).
- [ ] `POST /sanciones/{id}/convertir` con traza de actividad.
- [ ] Frontend: Directorio de clientes + Ficha de cliente (notas, timeline, acciones, deuda).

### Fase 5 — Histórico 4 años (P3)
- [ ] `tasks/backfill.py` (`build_historico_index`) reusando `classifier`/`parser`, sin LLM, reanudable.
- [ ] Acumulación diaria al índice.
- [ ] `services/historico.py` (búsqueda exacta + FTS) + complemento `teu_client.buscar_teu_por_nif`.
- [ ] Extracción on-demand (OpenAI) sobre seleccionados.
- [ ] Frontend: pantalla "Consulta por DNI/CIF", "Historial", y bloque histórico en la ficha.
- [ ] Documentar límite TEU (R-1) en la UI.

### Fase 6 — Documentos comerciales (P5)
- [ ] `services/documentos_pdf.py` (contrato y factura → PDF). Definir motor (WeasyPrint/Jinja2).
- [ ] Envío SMTP con adjuntos (`mailer`); endpoints `POST /clientes/{id}/contrato` y `/factura`.
- [ ] `DocumentoComercial` + actividad; numeración de facturas.
- [ ] UI: botones "Enviar contrato" / "Enviar factura" con formulario (precio / cuantía+concepto+adjuntos).

### Fase 7 — Rediseño visual completo (§8)
- [ ] Tokens + componentes base (sistema "Minimalismo Autoritario").
- [ ] Maquetar las pantallas según mockups, conectadas al backend.
- [ ] Dashboard con métricas (incluida tasa de conversión).

### Fase 8 — Validación, pruebas y entrega
- [ ] Pruebas backend (pipelines, enriquecimiento con mocks, histórico, PDFs/email con mocks SMTP).
- [ ] Recorrido E2E del flujo completo (captación → enriquecer → revisar → convertir → ficha → contrato/factura → histórico).
- [ ] Documentación de uso y operación (README operativo, `.env`, cómo lanzar backfill, límites).
- [ ] Datos de arranque: ingesta del bloque reciente + (opcional) backfill histórico.

---

## 11. Migraciones y compatibilidad

- Usar **Alembic** para cada cambio de modelo (`alembic revision --autogenerate -m "..."` →
  `alembic upgrade head`, ver `AGENTS.md`). En local, mantener coherencia con `Base.metadata.create_all`.
- Para `HistoricoDoc.tsv` (tsvector) y los índices GIN, escribir la migración a mano si autogenerate no los detecta.
- Idempotencia en todos los pipelines (por `boe_id`, por `codigo`, por número de factura).

---

## 12. Configuración (`.env`) y dependencias nuevas

Variables nuevas (añadir a `.env.example`):
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL` (unificar el default real vs `.env.example`; **decidir y documentar** el modelo).
- Enriquecimiento: `ENRICHMENT_MODE` (`on_demand`/`batch`), `WEB_SEARCH_PROVIDER` (`serpapi`/`bing`/`google_cse`/`none`), `WEB_SEARCH_API_KEY`, `GOOGLE_PLACES_API_KEY`, `EINFORMA_ENABLED`+`EINFORMA_API_KEY` (opcional), `ENRICHMENT_USE_LLM_DISAMBIGUATION` (default `false`).
- Histórico: `HISTORICO_BACKFILL_YEARS` (default 4), `TEU_PUBLIC_SEARCH_ENABLED`.
- Facturación/emisor: `EMISOR_NOMBRE`, `EMISOR_CIF`, `EMISOR_DIRECCION`, `EMISOR_IVA`, `FACTURA_SERIE`.
- SMTP (existentes): `SMTP_*`, `NOTIFICATION_EMAIL_TO`.

Dependencias probables a añadir (`backend/requirements.txt`): cliente de búsqueda web (según proveedor),
`weasyprint` (o `reportlab`) para PDFs, `jinja2` (plantillas), validadores de teléfono (`phonenumbers`).

---

## 13. Entregables (alineados con la propuesta §12)

- Definición funcional cerrada (este `PLAN.md` + Fase 0).
- Aplicación web operativa **en local** (Docker Compose).
- BD configurada (oportunidades, clientes, histórico, documentos).
- Panel de oportunidades con extracción automática y manual.
- **Enriquecimiento automático de contacto** (con manual fallback) — núcleo del valor.
- Módulo de clientes + fichas individuales (notas, actividad, acciones, contrato/factura por email).
- Histórico 4 años con búsqueda por cliente y extracción on-demand.
- Consulta por DNI/CIF.
- Acceso al documento original del BOE.
- Integración OpenAI (extracción estructurada).
- Documentación básica de uso y operación.

---

## 14. Riesgos y limitaciones (a vigilar)

- **R-1 (TEU 3 meses)**: histórico TEU/DGT anterior a 3 meses no recuperable públicamente → solo lo acumulado. Comunicado y reflejado en UI.
- **R-2 (DNI enmascarado en BOE ordinario)**: match por nombre menos preciso; mitigar con normalización + 4 dígitos visibles + matrícula/CIF.
- **R-3 (tasa de acierto del enriquecimiento)**: especialmente para particulares. Medir con muestra real; manual fallback siempre disponible.
- **R-4 (coste OpenAI)**: limitar extracción estructurada a 30 días + on-demand (ya contemplado). Coste a cargo de la clienta (su API key).
- **R-5 (variabilidad documental del BOE)**: documentos heterogéneos/incompletos; el sistema debe tolerar campos vacíos.
- **R-6 (RGPD)**: enriquecimiento de datos de contacto de personas físicas; base de licitud y revisión jurídica de la clienta.
- **R-7 (escala del backfill)**: 4 años de BOE es voluminoso; backfill reanudable por lotes, filtrando candidatos con el clasificador.

---

## 15. Decisiones abiertas (pendientes de la clienta / Fase 0)

1. **Plantilla de contrato** (texto exacto + placeholders) y **datos del emisor** de facturas (CIF, dirección, IVA, serie/numeración).
2. **Proveedor de búsqueda web** preferido para enriquecimiento (SerpAPI/Bing/Google CSE) y si se activa eInforma (de pago).
3. **Modelo de OpenAI** a fijar por defecto (hoy hay discrepancia entre `config.py` y `.env.example`).
4. **Materias/tipos de multa** prioritarios para etiquetado y filtros.
5. **Profundidad real del backfill** inicial a ejecutar en la puesta en marcha (4 años vs arranque progresivo).
6. **Definición de "deuda pendiente"** y "estado de prescripción" (cómo se calcula/marca).
