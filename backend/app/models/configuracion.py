from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConfiguracionApp(Base):
    """Runtime, user-editable configuration (one row per key).

    Everything here is something Judit is expected to change from the UI
    without touching ``.env`` or restarting containers: whether the daily
    pipeline runs the paid OpenAI extraction on its own, whether it uses the
    Batch API (cheaper, slower) or real-time calls, and the per-run caps.
    ``.env`` keeps the hard gates (API key, ``OPENAI_EXTRACTION_ENABLED``);
    this table only decides *how* an already-allowed feature is used. See
    ``services/configuracion.py`` for the typed view over these rows.
    """

    __tablename__ = "configuracion_app"

    clave: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
