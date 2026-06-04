# AGENTS.md

Repo: BOE Sanciones — FastAPI backend + Next.js frontend for scraping and tracking sanctions published in Spain's Boletín Oficial del Estado.

## Architecture

- Full stack via Docker Compose: FastAPI (8000) + Next.js (3000) + PostgreSQL 16 (5432) + Redis 7 (6379) + Celery worker/beat.
- Backend entrypoint: `uvicorn app.main:app` from `backend/`.
- Frontend entrypoint: `npm run dev` from `frontend/`.

## Quick start

```bash
cp .env.example .env
# Add OPENAI_API_KEY (required for extraction)
docker compose up --build
```

## Backend

- Python 3.12. Stack: FastAPI 0.115, SQLAlchemy 2.0 (asyncpg async + psycopg2 sync), Pydantic v2, Celery 5.4, Alembic 1.14.
- **Database**: `async_engine` for API, `sync_engine` for Celery tasks. Tables auto-created on startup via `lifespan` (`Base.metadata.create_all`).
- **Migrations**: Alembic is configured (`backend/alembic/`) but not auto-run in Docker Compose. After model changes, run manually inside the container:
  ```bash
  docker compose exec backend alembic revision --autogenerate -m "..."
  docker compose exec backend alembic upgrade head
  ```
- **Celery pipeline**: `app.tasks.scraping.run_daily_scraping` fetches BOE sumario → rule-based classifier → body verification → OpenAI structured extraction → TEU scraping. Beat schedule: 07:30 and 19:30 Europe/Madrid.
- **Task idempotency**: Scraping skips a date if `ScrapingRun.status == "completed"` already exists. Pass `force=True` to re-run.
- **Key directories**:
  - `app/api/` — FastAPI routers (dashboard, sanciones, documentos, scraping, notificaciones)
  - `app/services/` — business logic (boe_client, classifier, parser, extractor, notifier, teu_client)
  - `app/tasks/` — Celery tasks
  - `app/models/` — SQLAlchemy ORM models
  - `app/schemas/` — Pydantic schemas

## Frontend

- Next.js 16.1.6, React 19.2.3, Tailwind CSS v4.
- Path alias: `@/*` → `src/*`.
- Scripts: `npm run dev`, `npm run build`, `npm run lint` (ESLint only; no typecheck script).
- ESLint: `eslint-config-next` with TypeScript + core-web-vitals (`frontend/eslint.config.mjs`).
- Tailwind v4 is used via `@tailwindcss/postcss` in `postcss.config.mjs` — no separate `tailwind.config` file.

## Environment & config

- `.env` required at repo root. Key variables:
  - `OPENAI_API_KEY` — required for extraction.
  - `DATABASE_URL` / `DATABASE_URL_SYNC` — default points to `postgres` service inside Docker.
  - `REDIS_URL` — default `redis://redis:6379/0`.
  - `SMTP_*` / `NOTIFICATION_EMAIL_TO` — optional; email digest sent when new sanctions are found.
- Default OpenAI model in `backend/app/config.py` is `gpt-5.4-2026-03-05` (hardcoded default). `OPENAI_MODEL` env var overrides it.
- Frontend gets `NEXT_PUBLIC_API_URL=http://localhost:8000` from `docker-compose.yml`.

## Testing

- No test suites exist in backend or frontend yet.

## Style notes

- Spanish domain language throughout (BOE, sanciones, sancionado, seguimiento, notificacion, documento).
- Backend uses both async and sync SQLAlchemy sessions intentionally: async for API, sync for Celery tasks.
