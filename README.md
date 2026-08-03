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
| Frontend | Next.js 15 + Tailwind | 3000 |

## Requisitos

- Docker y Docker Compose
- OpenAI API key (solo cuando se habilite manualmente la extracción estructurada)

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
- **Proveedores de descubrimiento**: `fixture` (sin red, el único activo en pruebas), `searxng`
  (autoalojado, sin API key, recomendado por defecto en producción), `tavily` y `serper` (gestionados,
  con capas gratuitas verificadas en 2026). Google Custom Search y Brave Search API se investigaron y
  se descartaron: CSE está cerrado a nuevos clientes y se apaga el 1-ene-2027; Brave eliminó su capa
  gratuita en feb-2026. Un `paid_stub` documenta la interfaz para eInforma/Google Places sin
  integrarlos.
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

**Coste**: en desarrollo y pruebas, cero — sin proveedor de pago activo y sin llamadas reales. En
producción, con SearXNG autoalojado el coste marginal es prácticamente nulo; con Tavily hay 1.000
consultas/mes gratis sin tarjeta. Cualquier proveedor de pago queda en `paid_stub`, sin integrar.

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
| `/api/documentos` | GET | Listar documentos BOE |
| `/api/documentos/{id}` | GET | Detalle de un documento |
| `/api/notificaciones` | GET | Listar notificaciones |
| `/api/notificaciones/unread-count` | GET | Contador de no leidas |
| `/api/notificaciones/mark-read` | POST | Marcar como leidas |
| `/api/scraping/trigger` | POST | Disparar scraping manual |
| `/api/scraping/runs` | GET | Historial de ejecuciones |
| `/api/scraping/gaps` | GET | Fechas sin ejecución completada, sin encolar scraping |

## Migraciones y operación segura

El esquema está gobernado por Alembic. `docker compose up` ejecuta primero el servicio `migrate`:

- En una base nueva aplica todas las revisiones (`0001`→`0004`).
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

## Fuera de la sesión 2

Quedan deliberadamente para sesiones posteriores: histórico de 4 años (índice + búsqueda + extracción
on-demand), documentos comerciales (contrato/factura en PDF) y su envío por email, reglas fiscales,
proveedores de enriquecimiento de pago (eInforma, Google Places), scraping/login/extracción de
LinkedIn, enriquecimiento en lote habilitado por defecto, y el rediseño visual integral ("Minimalismo
Autoritario").

## Estructura del proyecto

```
boe-sanciones/
  docker-compose.yml
  .env.example
  backend/
    app/
      main.py           # FastAPI app
      config.py          # Settings
      database.py        # SQLAlchemy
      celery_app.py      # Celery config
      models/            # ORM models (incluye cliente.py, enriquecimiento.py)
      schemas/            # Pydantic schemas (incluye cliente.py)
      api/               # REST endpoints (incluye clientes.py, enriquecimiento.py)
      services/          # Business logic
        boe_client.py    # BOE API client
        classifier.py    # Rule-based classifier
        parser.py        # XML/HTML/PDF parser
        extractor.py     # OpenAI extraction
        notifier.py      # Email + in-app
        clientes.py      # Conversión idempotente, código CLI, deuda calculada
        enrichment/       # Cascada de enriquecimiento
          base.py         # Tipos compartidos (SearchProvider, EnrichmentResult)
          service.py      # Orquestación: descubrir → descargar → verificar → persistir
          patterns.py     # Regex de teléfono/email
          verify.py       # Verificación por evidencia (CIF/nombre)
          providers/      # fixture, searxng, tavily, serper, paid_stub
      tasks/             # Celery tasks (scraping.py, enrichment.py)
  frontend/
    src/app/             # Next.js pages (incluye clientes/, clientes/[id]/)
    src/lib/             # API client, types
```
