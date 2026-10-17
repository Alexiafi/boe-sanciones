from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

BATCH_ESTADOS = ("preparando", "enviado", "en_progreso", "completado", "fallido", "expirado", "cancelado")
BATCH_ITEM_ESTADOS = ("pendiente", "completado", "error")


class ExtraccionBatch(Base):
    """One OpenAI Batch API job (``services/openai_batch.py``).

    Created by the daily pipeline or the on-demand historical extraction when
    the runtime config selects ``extraccion_modo = "batch"``; polled by
    ``tasks/extraccion_batch.procesar_batches_pendientes`` until OpenAI
    reports a terminal status, at which point every item's result is applied
    exactly as the real-time path would have (same ``upsert_afectado``, same
    notifications, same client auto-assignment).
    """

    __tablename__ = "extracciones_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    # "diario" (BoeDocumento items) or "historico_cliente" (HistoricoResultado items).
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    scraping_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scraping_runs.id", ondelete="SET NULL"), nullable=True
    )
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="preparando")
    openai_batch_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    input_file_id: Mapped[Optional[str]] = mapped_column(String(100))
    output_file_id: Mapped[Optional[str]] = mapped_column(String(100))
    error_file_id: Mapped[Optional[str]] = mapped_column(String(100))
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sancionados_creados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_log: Mapped[Optional[str]] = mapped_column(Text)
    enviado_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ultimo_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finalizado_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items: Mapped[list["ExtraccionBatchItem"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="ExtraccionBatchItem.id"
    )

    __table_args__ = (
        CheckConstraint("tipo IN ('diario', 'historico_cliente')", name="ck_extracciones_batch_tipo"),
        CheckConstraint(
            "status IN ('preparando', 'enviado', 'en_progreso', 'completado', 'fallido', 'expirado', 'cancelado')",
            name="ck_extracciones_batch_status",
        ),
        Index("ix_extracciones_batch_status", "status"),
    )


class ExtraccionBatchItem(Base):
    """One request line inside a batch. Exactly one of ``boe_document_id`` /
    ``historico_resultado_id`` is set, matching the parent's ``tipo``."""

    __tablename__ = "extracciones_batch_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("extracciones_batch.id", ondelete="CASCADE"), nullable=False)
    custom_id: Mapped[str] = mapped_column(String(64), nullable=False)
    boe_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("boe_documentos.id", ondelete="CASCADE"), nullable=True
    )
    historico_resultado_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("historico_resultados.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    error: Mapped[Optional[str]] = mapped_column(Text)
    afectados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    batch: Mapped["ExtraccionBatch"] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("batch_id", "custom_id", name="uq_extracciones_batch_items_custom_id"),
        CheckConstraint("status IN ('pendiente', 'completado', 'error')", name="ck_extracciones_batch_items_status"),
        Index("ix_extracciones_batch_items_batch_id", "batch_id"),
        Index("ix_extracciones_batch_items_boe_document_id", "boe_document_id"),
    )
