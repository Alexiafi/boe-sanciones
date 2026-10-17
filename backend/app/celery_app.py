from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "boe_sanciones",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.scraping",
        "app.tasks.enrichment",
        "app.tasks.historico_backfill",
        "app.tasks.historico_extraccion",
        "app.tasks.extraccion_batch",
        "app.tasks.historico_reindexado",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Madrid",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # With acks_late, Redis re-delivers a task not acknowledged within the
    # visibility timeout (default 1 h). A long day's run (or a slow catch-up)
    # must never be handed to a second worker while it is still running.
    broker_transport_options={"visibility_timeout": 4 * 3600},
    broker_connection_retry_on_startup=True,
)

# Every scheduled entry is idempotent (see tasks/scraping.run_scraping): a
# date whose run already completed is skipped in one cheap query, and a date
# the BOE has not published yet returns "boe_no_publicado" without creating
# a run row. That is what makes the hourly retry safe: the morning edition
# appears somewhere between 07:30 and 08:30 Madrid, so the first slot that
# finds it wins and the rest are no-ops.
celery.conf.beat_schedule = {
    # Every half hour from 07:00 to 11:30 — the window in which the day's
    # edition and TEU supplement appear and Judit starts her calls (she needs
    # them by 9–10) — then hourly. Runs are incremental: a slot with nothing
    # new costs two cheap requests.
    "scrape-boe-today-morning": {
        "task": "app.tasks.scraping.run_daily_scraping",
        "schedule": crontab(minute="0,30", hour="7-11"),
    },
    "scrape-boe-today": {
        "task": "app.tasks.scraping.run_daily_scraping",
        # 12:30, 13:30 … 21:30 Europe/Madrid.
        "schedule": crontab(minute="30", hour="12-21"),
    },
    # Recent dates without a completed run (laptop off, failed attempt).
    # Also flips runs a dead worker left in "running" to "failed".
    "scrape-boe-catch-up": {
        "task": "app.tasks.scraping.catch_up_scraping",
        "schedule": crontab(minute="45", hour="8,14,20"),
    },
    # OpenAI Batch API jobs: cheap status polls; results are applied the
    # moment a job finishes.
    "openai-batches-poll": {
        "task": "app.tasks.extraccion_batch.procesar_batches_pendientes_task",
        "schedule": crontab(minute="*/5"),
    },
    # Razón social + phone/email of new company notices. A no-op unless
    # "enriquecimiento_automatico" is on in Configuración (paid searches).
    "enriquecimiento-automatico": {
        "task": "app.tasks.enrichment.enriquecimiento_automatico_task",
        "schedule": crontab(minute="*/15", hour="7-21"),
    },
}
