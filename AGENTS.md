# AGENTS.md

Repo: BOE Sanciones — FastAPI backend + Next.js frontend to capture, enrich, manage, and follow up on
sanctions published in Spain's Boletín Oficial del Estado (BOE), including a 4-year historical index,
commercial document generation (contrato/factura), and a "Minimalismo Autoritario" design system.

## Architecture

- Full stack via Docker Compose: FastAPI (8000) + Next.js (3000) + PostgreSQL 16 (5432) + Redis 7 (6379) +
  Celery worker/beat + optional SearXNG (8080, enrichment discovery) + optional Mailpit (1025/8025, dev email
  sandbox, profile `dev-mail`).
- Backend entrypoint: `uvicorn app.main:app` from `backend/`.
- Frontend entrypoint: `npm run dev` from `frontend/`.

## Quick start

```bash
cp .env.example .env
# Keep OPENAI_EXTRACTION_ENABLED=false, HISTORICO_BACKFILL_ENABLED=false, EMAIL_SENDING_ENABLED=false
# during development — see docs/GUIA_OPERATIVA.md for what each gate unlocks.
docker compose up --build
```

To verify without worker/beat (no real BOE/TEU network access):

```bash
docker compose up -d --build postgres migrate backend frontend
```

## Backend

- Python 3.12. Stack: FastAPI 0.115, SQLAlchemy 2.0 (asyncpg async + psycopg2 sync), Pydantic v2, Celery 5.4,
  Alembic 1.14, WeasyPrint 62 + Jinja2 (PDF generation).
- **Database**: `async_engine` for API routers, `sync_engine` for Celery tasks and a few sync-only service
  functions (search, document generation). Schema is governed **entirely by Alembic** — `app/main.py` has no
  `create_all`. `docker compose up` runs the `migrate` service first (`scripts/migrate.py`), which also
  bootstraps a pre-Alembic legacy database by stamping `0001_legacy_baseline` if the legacy tables match the
  expected shape.
  ```bash
  docker compose exec backend alembic revision --autogenerate -m "..."
  docker compose exec backend alembic upgrade head
  ```
  Current head: `0006_documentos_comerciales`. Chain: `0001_legacy_baseline` → `0002_opportunity_core` →
  `0003_enrichment_core` → `0004_clientes_crm` → `0005_historico_core` → `0006_documentos_comerciales`.
- **Celery pipelines**:
  - `app.tasks.scraping.run_daily_scraping` — BOE sumario → rule-based classifier → body verification →
    OpenAI structured extraction (gated) → TEU scraping → free daily accumulation into the historical index.
    Beat schedule: 07:30 and 19:30 Europe/Madrid. Idempotent per `(fecha_boe, tipo="diario")`.
  - `app.tasks.enrichment.*` — on-demand/batch contact enrichment (session 2). Gated by
    `ENRICHMENT_ENABLED` + a configured provider.
  - `app.tasks.historico_backfill.run_backfill_task` — **manual only, never in Celery beat**. Double-gated:
    `HISTORICO_BACKFILL_ENABLED=true` AND a confirmation token from `POST /api/historico/backfill/plan` that
    encodes the exact range and limits. Resumable via `HistoricoBackfillRun.cursor_fecha`. No OpenAI import
    anywhere in this module — structurally, not just by flag.
  - `app.tasks.historico_extraccion.extraer_historico_task` — on-demand OpenAI extraction over selected
    historical documents for an already-converted client. Same two OpenAI gates as the daily pipeline. Audited
    in `ScrapingRun(tipo="historico_cliente")`, which is excluded from the daily "already completed"/gaps
    checks (see `tipo` filtering in `tasks/scraping.py` and `api/scraping.py`).
- **Key directories**:
  - `app/api/` — routers: dashboard, sanciones, clientes, documentos (BOE), documentos_comerciales,
    enriquecimiento, historico, notificaciones, scraping.
  - `app/services/` — `boe_client`, `classifier`, `parser`, `extractor` (OpenAI), `notifier`, `mailer` (SMTP,
    gated), `oportunidades`, `clientes`, `documentos_comerciales`, `documentos_pdf` (WeasyPrint), `teu_client`,
    `enrichment/` (cascade + providers), `historico/` (`patterns.py` regex, `indexado.py` upsert,
    `busqueda.py` search, `teu_publico.py` optional TEU connector).
  - `app/tasks/` — `scraping.py`, `enrichment.py`, `historico_backfill.py`, `historico_extraccion.py`.
  - `app/models/`, `app/schemas/` — ORM models / Pydantic schemas, one module per domain.

## Frontend

- Next.js 16.1.6, React 19.2.3, Tailwind CSS v4.
- Path alias: `@/*` → `src/*`.
- Scripts: `npm run dev`, `npm run build`, `npm run lint`, `npm run typecheck` (`tsc --noEmit`), `npm run test`
  (Vitest), `npm run test:watch`.
- Design system: `src/components/ui/` (Button, Card, Chip/EstadoChip, ConfirmDialog, Field/Input/Select/
  Textarea, InfoRow, Notice, PageHeader, Pagination, Sidebar, Spinner, StatCard, EmptyState, ErrorState).
  Tokens ("Minimalismo Autoritario") live in `src/app/globals.css`; Inter is loaded via `next/font/google` in
  `layout.tsx`.
- ESLint: `eslint-config-next` with TypeScript + core-web-vitals + React hooks rules
  (`frontend/eslint.config.mjs`).
- Tailwind v4 via `@tailwindcss/postcss` in `postcss.config.mjs` — no separate `tailwind.config` file.

## Environment & config

- `.env` required at repo root; see `.env.example` for the full, commented list. Everything that costs money
  or touches a third party is **off by default**:
  - `OPENAI_API_KEY` / `OPENAI_EXTRACTION_ENABLED` — structured extraction (30-day pipeline + on-demand
    historical extraction). Requires both the flag and an explicit per-request confirmation.
  - `ENRICHMENT_ENABLED` / `ENRICHMENT_SEARCH_PROVIDER` — contact enrichment (session 2).
  - `HISTORICO_BACKFILL_ENABLED` — manual historical backfill (session 3). Off by default; see
    `docs/GUIA_OPERATIVA.md`.
  - `TEU_PUBLIC_SEARCH_ENABLED` — optional live TEU search connector. Off by default.
  - `EMAIL_SENDING_ENABLED` — SMTP send of contrato/factura or the daily digest. Off by default; point
    `SMTP_HOST=mailpit` at the `dev-mail` profile service for safe local testing.
  - `EMISOR_*` / `FACTURA_SERIE` / `DOCUMENTOS_DIR` — required before any contrato/factura can be generated;
    left blank on purpose (see `services/documentos_comerciales.validar`).
- Frontend gets `NEXT_PUBLIC_API_URL=http://localhost:8000` from `docker-compose.yml`.

## Testing

- **Backend**: pytest, run against an ephemeral PostgreSQL (never the dev database):
  ```bash
  docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
  ```
  Tests requiring a database are marked `@pytest.mark.integration` and skip automatically unless
  `TEST_DATABASE_URL_SYNC` is set (the test compose sets it). No test constructs a real OpenAI client or opens
  a real SMTP/HTTP socket — disabled-path tests assert this directly by monkeypatching the constructor to
  raise.
- **Frontend**: `npm run test` (Vitest + Testing Library, jsdom), `npm run typecheck`, `npm run lint`.

## Style notes

- Spanish domain language throughout (BOE, sanciones, sancionado, cliente, seguimiento, notificación,
  documento, histórico).
- Backend uses both async and sync SQLAlchemy sessions intentionally: async for API routers, sync for Celery
  tasks and a handful of service functions called from `run_in_threadpool`.
- Every feature that can incur real-world cost or contact a third party follows the same pattern: off by
  default, a clear reason string on the 409 when disabled, and an explicit confirmation required to proceed.
  Follow this pattern for any new such feature rather than inventing a new gating style.
