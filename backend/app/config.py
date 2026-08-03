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

    # Contact enrichment (session 2). Disabled and provider-less by default: no
    # code path may reach the network unless both ``enrichment_enabled`` is true
    # AND a concrete provider is configured. Batch is a second, independent gate
    # on top of that (see ENRICHMENT_BATCH_ENABLED).
    enrichment_enabled: bool = False
    enrichment_mode: str = "on_demand"  # on_demand | batch
    enrichment_search_provider: str = "none"  # none|fixture|searxng|tavily|serper
    searxng_url: str = ""
    tavily_api_key: str = ""
    serper_api_key: str = ""
    enrichment_min_confidence: float = Field(default=0.6, ge=0, le=1)
    enrichment_max_pages_per_attempt: int = Field(default=5, ge=1)
    enrichment_http_timeout: float = Field(default=10.0, gt=0)
    enrichment_rate_limit_per_domain_s: float = Field(default=2.0, ge=0)
    enrichment_cache_ttl_days: int = Field(default=30, ge=1)
    enrichment_respect_robots: bool = True
    enrichment_batch_enabled: bool = False
    enrichment_batch_max: int = Field(default=10, ge=1)
    enrichment_use_llm_disambiguation: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
