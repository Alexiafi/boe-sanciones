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
- **Seguimiento**: la abogada puede marcar estado de cada sancionado (pendiente, contactado, en gestion, descartado, resuelto)
- **Notificaciones**: alertas in-app y email digest cuando se detectan nuevas sanciones
- **Scraping manual**: ejecutar extraccion para una fecha concreta desde la UI

## API Endpoints

| Ruta | Metodo | Descripcion |
|---|---|---|
| `/api/dashboard/stats` | GET | Estadisticas del dashboard |
| `/api/sanciones` | GET | Listar sancionados (paginado, filtros) |
| `/api/sanciones/{id}` | GET | Detalle de un sancionado |
| `/api/sanciones/{id}` | PATCH | Editar únicamente estado de oportunidad, teléfono y email |
| `/api/sanciones/{id}/seguimientos` | GET/POST | Seguimientos de un sancionado |
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

- En una base nueva aplica todas las revisiones.
- En una base creada por la versión previa con `create_all`, valida las tablas y columnas legadas, marca la revisión baseline y aplica la actualización de oportunidades.
- Si la base no coincide con ese esquema, se detiene sin marcarla: haz una copia y revisa el diagnóstico antes de continuar.

No se ejecuta scraping al consultar oportunidades. La detección de huecos solo informa de fechas sin ejecución completada y puede incluir días sin publicación BOE.

## Filtros de oportunidades

`GET /api/sanciones` acepta `fecha_desde`, `fecha_hasta`, `estado_oportunidad`, `materia`, `tipo_persona`, `cuantia_min`, `cuantia_max` y `solo_con_contacto`. Sin rango explícito devuelve los últimos 30 días inclusivos.

## Pruebas

Las pruebas de backend usan fixtures/mocks y no contactan BOE, TEU, SMTP ni OpenAI. Ejecuta la batería completa con una base PostgreSQL efímera (no uses la base de trabajo local):

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

El contenedor aplica Alembic hasta `head` y configura `TEST_DATABASE_URL_SYNC`. Sin esa variable, solo se ejecutan las pruebas puras que no necesitan PostgreSQL.

## Fuera de la sesión 1

Quedan deliberadamente para sesiones posteriores: CRM y clientes, conversión, enriquecimiento de contacto, histórico/backfill, contratos, facturas, PDFs, reglas fiscales, rediseño visual completo y cualquier carga masiva o recorrido inicial de 30 días.

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
      models/            # ORM models
      schemas/           # Pydantic schemas
      api/               # REST endpoints
      services/          # Business logic
        boe_client.py    # BOE API client
        classifier.py    # Rule-based classifier
        parser.py        # XML/HTML/PDF parser
        extractor.py     # OpenAI extraction
        notifier.py      # Email + in-app
      tasks/             # Celery tasks
  frontend/
    src/app/             # Next.js pages
    src/lib/             # API client, types
```
