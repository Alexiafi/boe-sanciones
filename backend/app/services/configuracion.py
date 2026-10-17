"""Typed view over the ``configuracion_app`` key/value table.

``.env`` holds the hard gates (API key, ``OPENAI_EXTRACTION_ENABLED``,
SMTP…). This module holds what the operator changes day to day from the
"Configuración" screen, without a restart:

- ``extraccion_automatica`` — whether the scheduled daily pipeline runs the
  paid OpenAI extraction on its own (the manual trigger still has its own
  checkbox). Defaults to on: with the client's own key configured, the
  point of the product is that today's sanctions appear without anyone
  pressing a button.
- ``extraccion_modo`` — ``tiempo_real`` (per-document calls, results within
  the run) or ``batch`` (OpenAI Batch API: ~50% cheaper, results arrive
  asynchronously, up to 24h). Judit decides the trade-off herself.
- ``historico_extraccion_modo`` — same choice for the on-demand extraction
  over a client's historical documents (defaults to ``batch``: nobody is
  waiting on those, and it is where volume can grow).
- ``extraccion_max_docs_por_ejecucion`` — cap on OpenAI requests per daily
  run (real-time calls or batch lines). Overrides the ``.env`` value.
- ``teu_max_por_ejecucion`` — how many relevant TEU notifications the daily
  run downloads (the TEU publishes 600–1,200 relevant notices a day; 2026-09-18
  had 1,154).

Both a sync (Celery tasks) and an async (API) loader exist, sharing one
parser so defaults and validation live in a single place.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.models.configuracion import ConfiguracionApp

ModoExtraccion = Literal["tiempo_real", "batch"]


class ConfiguracionRuntime(BaseModel):
    extraccion_automatica: bool = True
    extraccion_modo: ModoExtraccion = "tiempo_real"
    historico_extraccion_modo: ModoExtraccion = "batch"
    extraccion_max_docs_por_ejecucion: int = Field(default=2_000, ge=0, le=5_000)
    teu_max_por_ejecucion: int = Field(default=2_000, ge=0, le=5_000)

    model_config = {"extra": "forbid"}


class ConfiguracionUpdate(BaseModel):
    """Partial update: only the keys present are written."""

    extraccion_automatica: bool | None = None
    extraccion_modo: ModoExtraccion | None = None
    historico_extraccion_modo: ModoExtraccion | None = None
    extraccion_max_docs_por_ejecucion: int | None = Field(default=None, ge=0, le=5_000)
    teu_max_por_ejecucion: int | None = Field(default=None, ge=0, le=5_000)

    model_config = {"extra": "forbid"}


def _defaults() -> dict[str, Any]:
    base = ConfiguracionRuntime()
    # The .env cap is the default until the operator overrides it from the UI.
    base.extraccion_max_docs_por_ejecucion = min(settings.openai_extraction_max_documents_per_run, 5_000)
    return base.model_dump()


def _parse(rows: list[ConfiguracionApp]) -> ConfiguracionRuntime:
    data = _defaults()
    for row in rows:
        if row.clave in data and isinstance(row.valor, dict) and "v" in row.valor:
            data[row.clave] = row.valor["v"]
    try:
        return ConfiguracionRuntime(**data)
    except Exception:  # a hand-edited bad value must never take the pipeline down
        return ConfiguracionRuntime(**_defaults())


def _upsert_stmt(clave: str, valor: Any):
    return (
        insert(ConfiguracionApp)
        .values(clave=clave, valor={"v": valor})
        .on_conflict_do_update(index_elements=[ConfiguracionApp.clave], set_={"valor": {"v": valor}})
    )


# --- sync (Celery tasks, run_in_threadpool) ---------------------------------

def leer_configuracion(db: Session) -> ConfiguracionRuntime:
    rows = db.execute(select(ConfiguracionApp)).scalars().all()
    return _parse(list(rows))


def guardar_configuracion(db: Session, cambios: ConfiguracionUpdate) -> ConfiguracionRuntime:
    for clave, valor in cambios.model_dump(exclude_none=True).items():
        db.execute(_upsert_stmt(clave, valor))
    db.flush()
    return leer_configuracion(db)


# --- async (API routers) ----------------------------------------------------

async def leer_configuracion_async(db: AsyncSession) -> ConfiguracionRuntime:
    rows = (await db.execute(select(ConfiguracionApp))).scalars().all()
    return _parse(list(rows))


async def guardar_configuracion_async(db: AsyncSession, cambios: ConfiguracionUpdate) -> ConfiguracionRuntime:
    for clave, valor in cambios.model_dump(exclude_none=True).items():
        await db.execute(_upsert_stmt(clave, valor))
    await db.flush()
    return await leer_configuracion_async(db)


def extraccion_disponible() -> tuple[bool, str | None]:
    """The permanent ``.env`` gate, shared by every caller that decides
    whether OpenAI may be called at all (daily pipeline, historical
    extraction, batch submission)."""
    if not settings.openai_extraction_enabled:
        return False, "La extracción OpenAI está desactivada (OPENAI_EXTRACTION_ENABLED=false)."
    if not settings.openai_api_key:
        return False, "Falta OPENAI_API_KEY en la configuración del servidor."
    return True, None
