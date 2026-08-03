from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScrapingRun(Base):
    __tablename__ = "scraping_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha_boe: Mapped[date] = mapped_column(Date, nullable=False)
    # "diario" (daily/manual BOE pipeline) or "historico_cliente" (on-demand
    # OpenAI extraction over selected historical documents, see
    # tasks/historico_extraccion.py). Historical backfill progress is tracked
    # separately in HistoricoBackfillRun — see that model's docstring for why
    # it must never share a row with a single fecha_boe like this table does:
    # run_scraping()'s "skip if already completed" check and
    # GET /api/scraping/gaps both key off (fecha_boe, status) here, and a
    # backfill row would make either silently treat a real date as covered.
    tipo: Mapped[str] = mapped_column(String(20), default="diario", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total_docs: Mapped[Optional[int]] = mapped_column(Integer)
    candidates: Mapped[Optional[int]] = mapped_column(Integer)
    extracted: Mapped[Optional[int]] = mapped_column(Integer)
    errors: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    error_log: Mapped[Optional[str]] = mapped_column(Text)
    extraction_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    extraction_provider: Mapped[Optional[str]] = mapped_column(String(50))
    extraction_limit: Mapped[Optional[int]] = mapped_column(Integer)
    extraction_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
