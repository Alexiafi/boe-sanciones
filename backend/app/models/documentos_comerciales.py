"""Commercial documents: contract/invoice templates and issued documents.

No contract text, tax data, invoice series or VAT rate is hardcoded anywhere
in this module or its templates — everything is parametrised via
``PlantillaDocumento``/``app.config.settings`` and validated explicitly by
``services/documentos_comerciales.validar`` before a PDF is ever generated.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PlantillaDocumento(Base):
    """A Jinja2 HTML template for a contrato or factura.

    Seeded provisionally (see migration 0006) with an explicit placeholder
    body so nobody mistakes it for the client's real contract text — see
    services/documentos_comerciales.py and app/templates/documentos/.
    """

    __tablename__ = "plantillas_documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    contenido_html: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("tipo IN ('contrato', 'factura')", name="ck_plantillas_documento_tipo"),
        Index("ix_plantillas_documento_tipo_activo", "tipo", "activo"),
    )


class DocumentoComercial(Base):
    """An issued contrato/factura PDF for a client.

    ``numero`` is unique (nullable — only invoices are numbered) and is
    allocated atomically by
    ``services/documentos_comerciales.allocate_numero_factura`` using the same
    PostgreSQL UPSERT-counter pattern as ``OP-``/``CLI-`` codes
    (``services/oportunidades.allocate_codigo``), so it is safe under
    concurrent requests and never reused.
    """

    __tablename__ = "documentos_comerciales"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    serie: Mapped[Optional[str]] = mapped_column(String(16))
    numero: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(Text)
    datos: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="generado")
    email_destino: Mapped[Optional[str]] = mapped_column(String(200))
    enviado_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped["Cliente"] = relationship(back_populates="documentos_comerciales")  # noqa: F821

    __table_args__ = (
        CheckConstraint("tipo IN ('contrato', 'factura')", name="ck_documentos_comerciales_tipo"),
        CheckConstraint(
            "estado IN ('generado', 'enviado', 'error_envio')",
            name="ck_documentos_comerciales_estado",
        ),
        Index("ix_documentos_comerciales_cliente_id", "cliente_id"),
    )


class ContadorFactura(Base):
    """One row per (serie, year); mirrors CodigoOportunidadContador/
    CodigoClienteContador's UPSERT-based allocation."""

    __tablename__ = "contadores_factura"

    serie: Mapped[str] = mapped_column(String(16))
    anio: Mapped[int] = mapped_column(Integer)
    ultimo_valor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (PrimaryKeyConstraint("serie", "anio", name="pk_contadores_factura"),)
