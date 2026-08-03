from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Postgres
    database_url: str = "postgresql+asyncpg://boe:boe_secret_2026@postgres:5432/boe_sanciones"
    database_url_sync: str = "postgresql://boe:boe_secret_2026@postgres:5432/boe_sanciones"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-2026-03-05"
    # Paid extraction is intentionally opt-in. A manual request must also set
    # ``permitir_extraccion_pago`` before the pipeline will call OpenAI.
    openai_extraction_enabled: bool = False
    openai_extraction_max_documents_per_run: int = Field(default=1, ge=0)

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    notification_email_to: str = ""

    # BOE
    boe_api_base_url: str = "https://www.boe.es/datosabiertos/api/boe"
    boe_base_url: str = "https://www.boe.es"

    # App
    scraping_interval_hours: int = 12
    gap_detection_max_days: int = Field(default=30, ge=1)
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
