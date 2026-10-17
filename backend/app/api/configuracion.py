"""Runtime configuration the operator edits from the "Configuración" screen.

Only *how* an already-enabled feature behaves lives here (real-time vs
batch, automatic daily extraction, per-run caps). The permanent gates stay
in ``.env`` and are reported read-only so the screen can explain why an
option has no effect yet (e.g. no API key)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.configuracion import (
    ConfiguracionRuntime,
    ConfiguracionUpdate,
    extraccion_disponible,
    guardar_configuracion_async,
    leer_configuracion_async,
)
from app.services.enrichment.service import enrichment_available
from app.services.mailer import email_sending_available

router = APIRouter(prefix="/api/configuracion", tags=["configuracion"])


class EstadoEntornoOut(BaseModel):
    """Read-only view of the ``.env`` gates, so the UI can say which runtime
    options are currently effective."""

    openai_extraccion_disponible: bool
    openai_extraccion_motivo: str | None = None
    openai_modelo: str
    enriquecimiento_disponible: bool
    enriquecimiento_motivo: str | None = None
    email_disponible: bool
    email_motivo: str | None = None
    backfill_historico_habilitado: bool


class ConfiguracionOut(BaseModel):
    configuracion: ConfiguracionRuntime
    entorno: EstadoEntornoOut


def _entorno() -> EstadoEntornoOut:
    openai_ok, openai_motivo = extraccion_disponible()
    enr_ok, enr_motivo = enrichment_available()
    mail_ok, mail_motivo = email_sending_available()
    return EstadoEntornoOut(
        openai_extraccion_disponible=openai_ok, openai_extraccion_motivo=openai_motivo,
        openai_modelo=settings.openai_model,
        enriquecimiento_disponible=enr_ok, enriquecimiento_motivo=enr_motivo,
        email_disponible=mail_ok, email_motivo=mail_motivo,
        backfill_historico_habilitado=settings.historico_backfill_enabled,
    )


@router.get("", response_model=ConfiguracionOut)
async def get_configuracion(db: AsyncSession = Depends(get_db)):
    return ConfiguracionOut(configuracion=await leer_configuracion_async(db), entorno=_entorno())


@router.put("", response_model=ConfiguracionOut)
async def put_configuracion(data: ConfiguracionUpdate, db: AsyncSession = Depends(get_db)):
    configuracion = await guardar_configuracion_async(db, data)
    await db.commit()
    return ConfiguracionOut(configuracion=configuracion, entorno=_entorno())
