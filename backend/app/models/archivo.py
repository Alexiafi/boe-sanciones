"""Archived copy of the original BOE/TEU document bytes.

The BOE notifications supplement and the TEU remove documents from their
public sites after a period. This table keeps the exact bytes the pipeline
downloaded (PDF, HTML or XML), keyed by ``boe_id`` — the identifier namespace
shared by ``boe_documentos`` (operational pipeline) and ``historico_docs``
(historical index), so one archived copy serves both. Writes are idempotent:
the first archived copy wins and is never overwritten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocumentoArchivo(Base):
    __tablename__ = "documento_archivos"

    id: Mapped[int] = mapped_column(primary_key=True)
    boe_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    contenido: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    url_origen: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
