from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BoeDocumento(Base):
    __tablename__ = "boe_documentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    boe_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    fecha_publicacion: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    diario_numero: Mapped[Optional[int]]
    seccion_codigo: Mapped[Optional[str]] = mapped_column(String(10))
    seccion_nombre: Mapped[Optional[str]] = mapped_column(String(200))
    departamento_codigo: Mapped[Optional[str]] = mapped_column(String(50))
    departamento_nombre: Mapped[Optional[str]] = mapped_column(String(500))
    epigrafe_nombre: Mapped[Optional[str]] = mapped_column(String(500))
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    texto_plano: Mapped[Optional[str]] = mapped_column(Text)
    hash_texto: Mapped[Optional[str]] = mapped_column(String(64))
    familia_sancionadora: Mapped[Optional[str]] = mapped_column(String(50))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    match_rules: Mapped[Optional[dict]] = mapped_column(JSONB)
    url_html: Mapped[Optional[str]] = mapped_column(Text)
    url_xml: Mapped[Optional[str]] = mapped_column(Text)
    url_pdf: Mapped[Optional[str]] = mapped_column(Text)
    raw_sumario_item: Mapped[Optional[dict]] = mapped_column(JSONB)
    source: Mapped[Optional[str]] = mapped_column(String(50), default="boe_api_sumario")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sancionados: Mapped[list["Sancionado"]] = relationship(  # noqa: F821
        back_populates="documento", cascade="all, delete-orphan"
    )
