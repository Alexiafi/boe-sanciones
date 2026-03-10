from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "boe_sanciones",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.scraping"],
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
)

celery.conf.beat_schedule = {
    "scrape-boe-morning": {
        "task": "app.tasks.scraping.run_daily_scraping",
        "schedule": crontab(hour="7", minute="30"),
    },
    "scrape-boe-evening": {
        "task": "app.tasks.scraping.run_daily_scraping",
        "schedule": crontab(hour="19", minute="30"),
    },
}
