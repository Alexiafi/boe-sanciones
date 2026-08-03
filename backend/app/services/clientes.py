"""Persistence helpers for the Clientes/CRM core.

Async, unlike services/oportunidades.py: conversion is plain DB logic (no
external I/O, no cost concerns), invoked directly from the async API router,
so it uses AsyncSession the same way the rest of api/sanciones.py already
does — no Celery task needed for something this fast and deterministic.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import ActividadCliente, Cliente, CodigoClienteContador
from app.models.sancionado import Sancionado

CLIENT_STATES = ("activo", "inactivo")


async def allocate_codigo_cliente(db: AsyncSession, year: int | None = None) -> str:
    """Allocate the next annual CLI-YYYY-NNNN code atomically in PostgreSQL.

    Mirrors app.services.oportunidades.allocate_codigo's UPSERT pattern exactly
    (same concurrency guarantee, verified there under concurrent allocation),
    against its own yearly counter table so opportunity and client numbering
    never share state or collide.
    """
    year = year or date.today().year
    stmt = (
        insert(CodigoClienteContador)
        .values(anio=year, ultimo_valor=1)
        .on_conflict_do_update(
            index_elements=[CodigoClienteContador.anio],
            set_={"ultimo_valor": CodigoClienteContador.ultimo_valor + 1},
        )
        .returning(CodigoClienteContador.ultimo_valor)
    )
    sequence = (await db.execute(stmt)).scalar_one()
    return f"CLI-{year}-{sequence:04d}"


def _split_identifier(sancionado: Sancionado) -> tuple[str | None, str | None]:
    """Return (cif_nif, dni_nie) from the opportunity's single identificador
    field, using tipo_identificador when known and falling back to
    tipo_persona otherwise."""
    identificador = sancionado.identificador
    if not identificador:
        return None, None
    tipo = (sancionado.tipo_identificador or "").upper()
    if tipo == "CIF":
        return identificador, None
    if tipo in ("NIF", "NIE", "DNI"):
        return None, identificador
    if sancionado.tipo_persona == "juridica":
        return identificador, None
    return None, identificador


async def find_existing_cliente(db: AsyncSession, sancionado: Sancionado) -> Cliente | None:
    """Look up a Cliente already linked to this Sancionado, by either path:
    the FK on the opportunity or the unique FK on the client. The two can
    diverge only if a prior request committed the Cliente but crashed before
    updating ``sancionado.cliente_id`` — this covers that case too."""
    if sancionado.cliente_id is not None:
        existing = await db.get(Cliente, sancionado.cliente_id)
        if existing is not None:
            return existing
    return (
        await db.execute(select(Cliente).where(Cliente.sancion_origen_id == sancionado.id))
    ).scalar_one_or_none()


async def convertir_oportunidad(db: AsyncSession, sancionado: Sancionado) -> tuple[Cliente, bool]:
    """Convert a Sancionado into a Cliente.

    Idempotent: a second call for the same Sancionado returns the existing
    Cliente unchanged (``created=False``), never a duplicate. The
    ``clientes.sancion_origen_id`` unique constraint is the concurrency-safe
    backstop if two requests race past this function's own check; the caller
    (api/clientes.py) catches that IntegrityError and re-resolves to the
    winning row rather than surfacing a 500.
    """
    existing = await find_existing_cliente(db, sancionado)
    if existing is not None:
        sancionado.cliente_id = existing.id
        sancionado.estado_oportunidad = "cliente"
        return existing, False

    cif_nif, dni_nie = _split_identifier(sancionado)
    cliente = Cliente(
        codigo=await allocate_codigo_cliente(db),
        nombre_razon_social=sancionado.nombre or f"Oportunidad {sancionado.codigo}",
        tipo_persona=sancionado.tipo_persona,
        cif_nif=cif_nif,
        dni_nie=dni_nie,
        matriculas=[sancionado.matricula_coche] if sancionado.matricula_coche else [],
        telefono=sancionado.telefono,
        email=sancionado.email,
        direccion_fiscal=sancionado.direccion,
        localidad=sancionado.localidad,
        provincia=sancionado.provincia,
        codigo_postal=sancionado.codigo_postal,
        web=sancionado.web,
        sancion_origen_id=sancionado.id,
    )
    db.add(cliente)
    await db.flush()

    sancionado.cliente_id = cliente.id
    # This is the only code path allowed to set "cliente": PATCH rejects it
    # (session 1), so conversion is the sole way an opportunity reaches it.
    sancionado.estado_oportunidad = "cliente"

    db.add(ActividadCliente(
        cliente_id=cliente.id, tipo="conversion", titulo="Conversión desde oportunidad",
        detalle=f"Convertido desde la oportunidad {sancionado.codigo}",
        datos={"sancionado_id": sancionado.id, "codigo_oportunidad": sancionado.codigo},
    ))
    await db.flush()
    return cliente, True


async def deuda_pendiente_eur(db: AsyncSession, cliente_id: int) -> float:
    """Sum of importe_multa_eur/importe_deuda_eur across every Sancionado
    linked to this client. Always computed on read, never a stored column, so
    it can't go stale relative to the underlying sanciones."""
    amount = func.coalesce(Sancionado.importe_multa_eur, Sancionado.importe_deuda_eur, 0)
    total = (
        await db.execute(select(func.coalesce(func.sum(amount), 0)).where(Sancionado.cliente_id == cliente_id))
    ).scalar_one()
    return float(total)
