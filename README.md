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
- OpenAI API key (para extraccion estructurada)

## Inicio rapido

```bash
# 1. Configurar variables de entorno
cp .env.example .env
# Edita .env con tu OPENAI_API_KEY y configuracion SMTP

# 2. Levantar todos los servicios
docker compose up --build

# 3. Acceder
# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
```

## Funcionalidades

- **Scraping automatico**: extrae el sumario diario del BOE via API oficial cada 12 horas
- **Clasificacion por reglas**: filtra documentos sancionadores usando patrones STRONG/MEDIUM
- **Extraccion con IA**: usa OpenAI structured outputs para extraer datos de sancionados (nombre, CIF/NIF, direccion, multa, expediente, plazos, base legal)
- **Seguimiento**: la abogada puede marcar estado de cada sancionado (pendiente, contactado, en gestion, descartado, resuelto)
- **Notificaciones**: alertas in-app y email digest cuando se detectan nuevas sanciones
- **Scraping manual**: ejecutar extraccion para una fecha concreta desde la UI

## API Endpoints

| Ruta | Metodo | Descripcion |
|---|---|---|
| `/api/dashboard/stats` | GET | Estadisticas del dashboard |
| `/api/sanciones` | GET | Listar sancionados (paginado, filtros) |
| `/api/sanciones/{id}` | GET | Detalle de un sancionado |
| `/api/sanciones/{id}/seguimientos` | GET/POST | Seguimientos de un sancionado |
| `/api/documentos` | GET | Listar documentos BOE |
| `/api/documentos/{id}` | GET | Detalle de un documento |
| `/api/notificaciones` | GET | Listar notificaciones |
| `/api/notificaciones/unread-count` | GET | Contador de no leidas |
| `/api/notificaciones/mark-read` | POST | Marcar como leidas |
| `/api/scraping/trigger` | POST | Disparar scraping manual |
| `/api/scraping/runs` | GET | Historial de ejecuciones |

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
