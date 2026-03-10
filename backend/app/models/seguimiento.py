from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Seguimiento(Base):
    __tablename__ = "seguimientos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sancionado_id: Mapped[int] = mapped_column(ForeignKey("sancionados.id"), index=True)
    nota: Mapped[Optional[str]] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(50), default="pendiente")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sancionado: Mapped["Sancionado"] = relationship(back_populates="seguimientos")  # noqa: F821
