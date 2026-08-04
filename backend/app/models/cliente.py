from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Cliente(Base):
    """A converted opportunity. ``sancion_origen_id`` is unique: one Sancionado
    converts to at most one Cliente, which is what makes the conversion
    endpoint idempotent (see services/clientes.py)."""

    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)

    nombre_razon_social: Mapped[str] = mapped_column(String(500), nullable=False)
    tipo_persona: Mapped[Optional[str]] = mapped_column(String(20))
    cif_nif: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    dni_nie: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    matriculas: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    persona_contacto: Mapped[Optional[str]] = mapped_column(String(200))
    telefono: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    direccion_fiscal: Mapped[Optional[str]] = mapped_column(Text)
    localidad: Mapped[Optional[str]] = mapped_column(String(200))
    provincia: Mapped[Optional[str]] = mapped_column(String(200))
    codigo_postal: Mapped[Optional[str]] = mapped_column(String(10))
    web: Mapped[Optional[str]] = mapped_column(String(500))
    sector: Mapped[Optional[str]] = mapped_column(String(200))

    estado_cliente: Mapped[str] = mapped_column(String(20), default="activo", nullable=False)
    fecha_contrato: Mapped[Optional[date]] = mapped_column(Date)
    precio_contrato: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))

    # Not an ORM relationship on purpose: Sancionado.cliente_id and this column
    # form two independent FK paths between the same two tables, which would
    # make an implicit relationship() ambiguous. The API layer queries both
    # directions explicitly instead.
    sancion_origen_id: Mapped[int] = mapped_column(ForeignKey("sancionados.id"), unique=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    notas: Mapped[list["NotaCliente"]] = relationship(back_populates="cliente", cascade="all, delete-orphan")
    actividades: Mapped[list["ActividadCliente"]] = relationship(back_populates="cliente", cascade="all, delete-orphan")
    acciones: Mapped[list["AccionAgendada"]] = relationship(back_populates="cliente", cascade="all, delete-orphan")
    historico_resultados: Mapped[list["HistoricoResultado"]] = relationship(  # noqa: F821
        back_populates="cliente", cascade="all, delete-orphan"
    )
    documentos_comerciales: Mapped[list["DocumentoComercial"]] = relationship(  # noqa: F821
        cascade="all, delete-orphan"
    )
    # foreign_keys pinned to cliente_id only: VinculoCliente.cliente_vinculado_id
    # is the second, independent FK path to this same table (the holding
    # case), which would otherwise make this relationship ambiguous.
    vinculos: Mapped[list["VinculoCliente"]] = relationship(
        back_populates="cliente", cascade="all, delete-orphan", foreign_keys="VinculoCliente.cliente_id"
    )


class CodigoClienteContador(Base):
    """One row per year; mirrors CodigoOportunidadContador's UPSERT-based
    allocation (see services/oportunidades.allocate_codigo), reused verbatim
    in services/clientes.allocate_codigo_cliente for CLI-YYYY-NNNN codes."""

    __tablename__ = "codigo_cliente_contadores"

    anio: Mapped[int] = mapped_column(Integer, primary_key=True)
    ultimo_valor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NotaCliente(Base):
    __tablename__ = "notas_cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True, nullable=False)
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    autor: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped["Cliente"] = relationship(back_populates="notas")


class ActividadCliente(Base):
    """Timeline entry. ``tipo`` in llamada/email/pago/nota/conversion/sistema."""

    __tablename__ = "actividades_cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    detalle: Mapped[Optional[str]] = mapped_column(Text)
    datos: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped["Cliente"] = relationship(back_populates="actividades")


class AccionAgendada(Base):
    """Scheduled action (e.g. "agendar llamada"). ``tipo`` in llamada/email/tarea."""

    __tablename__ = "acciones_agendadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    fecha_programada: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", nullable=False)
    notas: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cliente: Mapped["Cliente"] = relationship(back_populates="acciones")


class VinculoCliente(Base):
    """A person or company linked to a client account (administrador, conductor,
    empleado, matriz, filial…). ``rol`` is free text on purpose — Judit decides
    the taxonomy per case, not us.

    Either ``nombre`` or ``cliente_vinculado_id`` must be set (enforced in the
    schema, see schemas/cliente.py): a linked entity is either a lightweight
    profile living entirely inside the parent client's page, or a pointer to
    another Cliente that already has its own ficha (the holding case — matriz
    contracts, but a filial with its own Cliente row shows up here too).
    Sanciones tag themselves to a vinculo via ``Sancionado.vinculo_id``, and
    historical search results the same way via ``HistoricoResultado.vinculo_id``.
    """

    __tablename__ = "vinculos_cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True, nullable=False)
    cliente_vinculado_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clientes.id"), nullable=True)
    rol: Mapped[str] = mapped_column(String(100), nullable=False)
    nombre: Mapped[Optional[str]] = mapped_column(String(500))
    tipo_persona: Mapped[Optional[str]] = mapped_column(String(20))
    identificador: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    tipo_identificador: Mapped[Optional[str]] = mapped_column(String(20))
    telefono: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(200))
    notas: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cliente: Mapped["Cliente"] = relationship(back_populates="vinculos", foreign_keys=[cliente_id])
