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
    enrichment_search_provider: str = "none"  # none|fixture|searxng|dataforseo|serper|tavily
    searxng_url: str = ""
    # Tavily is NOT recommended: its ToS prohibits "unsolicited marketing
    # proposals" (see providers/tavily.py). Kept configurable only for a future
    # session with written authorization from Tavily.
    tavily_api_key: str = ""
    serper_api_key: str = ""
    # DataForSEO Google Organic SERP API — recommended primary provider
    # (deep-research-report (14).md, 2026-08-03): near-zero effective cost,
    # prepaid balance never expires. HTTP Basic auth with login/password from
    # the DataForSEO dashboard (not an API key). Requires a prepaid balance
    # (their minimum top-up is $50) before it returns real results.
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    dataforseo_location_name: str = "Spain"
    dataforseo_language_code: str = "es"
    enrichment_min_confidence: float = Field(default=0.6, ge=0, le=1)
    enrichment_max_pages_per_attempt: int = Field(default=5, ge=1)
    enrichment_http_timeout: float = Field(default=10.0, gt=0)
    enrichment_rate_limit_per_domain_s: float = Field(default=2.0, ge=0)
    enrichment_cache_ttl_days: int = Field(default=30, ge=1)
    enrichment_respect_robots: bool = True
    enrichment_batch_enabled: bool = False
    enrichment_batch_max: int = Field(default=10, ge=1)
    enrichment_use_llm_disambiguation: bool = False

    # Historical index / backfill (session 3). Disabled by default: the daily
    # accumulation (free — reuses text already downloaded by the daily
    # pipeline) is on by default, but the manual backfill over past years is
    # gated behind BOTH this flag AND an explicit, range-bound confirmation
    # token on every request (see tasks/historico_backfill.py).
    historico_backfill_enabled: bool = False
    historico_backfill_years: int = Field(default=4, ge=1, le=10)
    historico_backfill_max_dias_por_lote: int = Field(default=5, ge=1, le=60)
    historico_backfill_max_docs_por_lote: int = Field(default=200, ge=1, le=5_000)
    historico_backfill_delay_s: float = Field(default=1.0, ge=0)
    # Storing the plain text (and now the raw bytes, see services/archivo.py)
    # costs nothing and is exactly what keeps a document usable after the
    # source removes it — so it defaults to on.
    historico_backfill_store_text: bool = True
    historico_indexado_diario_enabled: bool = True
    historico_extraccion_max_docs_por_peticion: int = Field(default=3, ge=0)

    # Optional TEU public-search connector (session 3). Off by default and
    # provider-less by default; see services/historico/teu_publico.py. Never
    # called from any automatic path (no beat schedule, no default-on flag).
    teu_public_search_enabled: bool = False
    teu_public_search_provider: str = "none"  # none|fixture|http
    teu_public_search_max_por_consulta: int = Field(default=50, ge=1, le=200)

    # Commercial documents (session 3). Nothing here is invented — every field
    # is required and validated explicitly before a PDF is generated (see
    # services/documentos_comerciales.validar). Empty by default on purpose.
    emisor_nombre: str = ""
    emisor_cif: str = ""
    emisor_direccion: str = ""
    emisor_email: str = ""
    emisor_iva_porcentaje: float = Field(default=21.0, ge=0, le=100)
    factura_serie: str = ""
    documentos_dir: str = "/app/data/documentos"

    # Email sending (session 3). Off by default; POST endpoints additionally
    # require confirmar=true. Point SMTP_HOST/SMTP_PORT at the Mailpit dev
    # service (docker-compose.yml, profile "dev-mail") for a safe local
    # mailbox — see services/mailer.py and README.md.
    email_sending_enabled: bool = False
    smtp_use_tls: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
