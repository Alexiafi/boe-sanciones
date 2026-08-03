from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CodigoOportunidadContador(Base):
    """One row per publication year; allocation is done with an UPSERT."""

    __tablename__ = "codigo_oportunidad_contadores"

    anio: Mapped[int] = mapped_column(Integer, primary_key=True)
    ultimo_valor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
