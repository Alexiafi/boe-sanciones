from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(50))
    titulo: Mapped[str] = mapped_column(String(500))
    mensaje: Mapped[Optional[str]] = mapped_column(Text)
    leida: Mapped[bool] = mapped_column(Boolean, default=False)
    sancionado_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sancionados.id"), nullable=True)
    # Set whenever the notification concerns an existing client (new sanction
    # for a client or one of their vínculos) — what the "Solo mis clientes"
    # filter in /notificaciones matches on.
    cliente_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clientes.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sancionado: Mapped[Optional["Sancionado"]] = relationship(back_populates="notificaciones")  # noqa: F821
