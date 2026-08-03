from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EnriquecimientoIntento(Base):
    """One row per contact-enrichment attempt, successful or not.

    Recorded unconditionally — including ``no_encontrado`` and ``error`` outcomes —
    so cost and effectiveness can be audited without re-running anything.
    """

    __tablename__ = "enriquecimiento_intentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sancionado_id: Mapped[int] = mapped_column(ForeignKey("sancionados.id"), index=True, nullable=False)
    proveedor: Mapped[str] = mapped_column(String(50), nullable=False)
    consulta: Mapped[Optional[str]] = mapped_column(Text)
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    url_origen: Mapped[Optional[str]] = mapped_column(String(500))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    evidencia: Mapped[Optional[str]] = mapped_column(Text)
    coste_estimado_eur: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), default=0)
    duracion_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EnriquecimientoCache(Base):
    """Caches provider responses by query/domain hash to avoid repeat cost."""

    __tablename__ = "enriquecimiento_cache"

    clave: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
