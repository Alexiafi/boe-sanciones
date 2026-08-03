from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Sancionado(Base):
    __tablename__ = "sancionados"

    id: Mapped[int] = mapped_column(primary_key=True)
    boe_document_id: Mapped[int] = mapped_column(ForeignKey("boe_documentos.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    estado_oportunidad: Mapped[str] = mapped_column(String(20), default="nueva", nullable=False)
    origen_clave: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    nombre: Mapped[Optional[str]] = mapped_column(String(500), index=True)
    tipo_persona: Mapped[Optional[str]] = mapped_column(String(20))
    identificador: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    tipo_identificador: Mapped[Optional[str]] = mapped_column(String(20))
    direccion: Mapped[Optional[str]] = mapped_column(Text)
    localidad: Mapped[Optional[str]] = mapped_column(String(200))
    provincia: Mapped[Optional[str]] = mapped_column(String(200))
    codigo_postal: Mapped[Optional[str]] = mapped_column(String(10))
    telefono: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    matricula_coche: Mapped[Optional[str]] = mapped_column(String(20))

    importe_multa_eur: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    tipo_infraccion: Mapped[Optional[str]] = mapped_column(String(50))
    razon_sancion: Mapped[Optional[str]] = mapped_column(Text)
    expediente: Mapped[Optional[str]] = mapped_column(String(200))
    estado_publicacion: Mapped[Optional[str]] = mapped_column(String(50))
    tipo_procedimiento: Mapped[Optional[str]] = mapped_column(String(30))
    importe_deuda_eur: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))

    plazo_notificacion: Mapped[Optional[str]] = mapped_column(String(200))
    plazo_alegaciones: Mapped[Optional[str]] = mapped_column(String(200))
    plazo_recurso: Mapped[Optional[str]] = mapped_column(String(200))
    plazo_pago_voluntario: Mapped[Optional[str]] = mapped_column(String(200))
    base_legal: Mapped[Optional[str]] = mapped_column(Text)
    organismo_emisor: Mapped[Optional[str]] = mapped_column(String(500))
    dominio_material: Mapped[Optional[str]] = mapped_column(String(200))
    fecha_resolucion: Mapped[Optional[date]] = mapped_column(Date)
    observaciones: Mapped[Optional[str]] = mapped_column(Text)

    # Contact enrichment (session 2). ``contacto_estado`` tracks provenance
    # independently of whether telefono/email are filled, so the UI can show
    # "no encontrado" (searched, nothing found) distinctly from "pendiente"
    # (never attempted) and "manual" (user-entered, never overwritten by
    # automatic enrichment).
    web: Mapped[Optional[str]] = mapped_column(String(500))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))
    telefono_secundario: Mapped[Optional[str]] = mapped_column(String(50))
    contacto_estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False)
    contacto_fuente: Mapped[Optional[str]] = mapped_column(String(50))
    contacto_url: Mapped[Optional[str]] = mapped_column(String(500))
    contacto_confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    contacto_actualizado_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Set once this opportunity converts to a client (Fase 4). The column itself
    # was added in migration 0003 (before ``clientes`` existed); its FK
    # constraint is added by migration 0004 alongside the ``clientes`` table.
    # No ORM relationship() here: Cliente.sancion_origen_id is a second,
    # independent FK back to this table, which would make an implicit
    # relationship ambiguous — see cliente.py's comment on that column.
    cliente_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("clientes.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documento: Mapped["BoeDocumento"] = relationship(back_populates="sancionados")  # noqa: F821
    seguimientos: Mapped[list["Seguimiento"]] = relationship(  # noqa: F821
        back_populates="sancionado", cascade="all, delete-orphan"
    )
    notificaciones: Mapped[list["Notificacion"]] = relationship(  # noqa: F821
        back_populates="sancionado", cascade="all, delete-orphan"
    )
