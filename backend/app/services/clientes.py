"""Persistence helpers for the Clientes/CRM core.

Async, unlike services/oportunidades.py: conversion is plain DB logic (no
external I/O, no cost concerns), invoked directly from the async API router,
so it uses AsyncSession the same way the rest of api/sanciones.py already
does — no Celery task needed for something this fast and deterministic.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import (
    AccionAgendada, ActividadCliente, Cliente, CodigoClienteContador, NotaCliente, VinculoCliente,
)
from app.models.documentos_comerciales import DocumentoComercial
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado

logger = logging.getLogger(__name__)

# activo    = real, contracted client
# informado = converted prospect Judit only sends information to
# inactivo  = no longer a client
CLIENT_STATES = ("activo", "informado", "inactivo")


class ClienteConFacturas(Exception):
    """Issued invoices must be kept (accounting records): such a client is
    deactivated, never deleted."""

    def __init__(self, cuantas: int) -> None:
        self.cuantas = cuantas
        super().__init__(f"El cliente tiene {cuantas} factura(s) emitida(s)")


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
    # PATCH rejects "cliente" (session 1) — the only ways an opportunity
    # reaches it are this manual conversion and the automatic assignment in
    # services/vinculos.asignar_sancion_a_cliente (session 4).
    sancionado.estado_oportunidad = "cliente"

    # The alert that announced this sanction now concerns a client: tag it so
    # the "Solo mis clientes" filter in /notificaciones includes it.
    await db.execute(
        update(Notificacion)
        .where(Notificacion.sancionado_id == sancionado.id, Notificacion.cliente_id.is_(None))
        .values(cliente_id=cliente.id)
    )

    db.add(ActividadCliente(
        cliente_id=cliente.id, tipo="conversion", titulo="Conversión desde oportunidad",
        detalle=f"Convertido desde la oportunidad {sancionado.codigo}",
        datos={"sancionado_id": sancionado.id, "codigo_oportunidad": sancionado.codigo},
    ))
    await db.flush()
    return cliente, True


def _split_identifier_vinculo(vinculo: VinculoCliente) -> tuple[str | None, str | None]:
    identificador = (vinculo.identificador or "").strip() or None
    if not identificador:
        return None, None
    tipo = (vinculo.tipo_identificador or "").upper()
    if tipo == "CIF":
        return identificador, None
    if tipo in ("NIF", "NIE", "DNI"):
        return None, identificador
    if vinculo.tipo_persona == "juridica":
        return identificador, None
    # A Spanish CIF starts with a letter and ends in a digit or letter; a DNI
    # starts with digits, a NIE with X/Y/Z. Only guess when unambiguous.
    if identificador[0].isalpha() and identificador[0].upper() not in ("X", "Y", "Z"):
        return identificador, None
    return None, identificador


def _rol_reciproco(rol: str) -> str:
    lowered = rol.lower()
    if "administrador" in lowered or "administradora" in lowered:
        return "Sociedad administrada"
    if "conductor" in lowered:
        return "Titular del vehículo"
    if "filial" in lowered:
        return "Matriz"
    if "matriz" in lowered:
        return "Filial"
    return "Entidad vinculada"


async def convertir_vinculo(db: AsyncSession, cliente_padre: Cliente, vinculo: VinculoCliente) -> tuple[Cliente, bool]:
    """Promote a vínculo (the administrador of a company that is already a
    client, a driver, a subsidiary…) to a Cliente with its own ficha.

    For Judit these are two prospects, not one: the company's sanctions and
    the administrador's own sanctions are separate deals. The link is kept
    both ways — ``vinculo.cliente_vinculado_id`` on the parent's card and a
    reciprocal vínculo on the new ficha — so either page reaches the other.

    Sanctions already tagged to this vínculo on the parent (``Sancionado.
    vinculo_id``) move to the new client: they were always that person's,
    and their own ficha is where they get worked. Idempotent: a vínculo that
    already points at a client returns it unchanged (``created=False``).
    """
    if vinculo.cliente_vinculado_id is not None:
        existing = await db.get(Cliente, vinculo.cliente_vinculado_id)
        if existing is not None:
            return existing, False

    cif_nif, dni_nie = _split_identifier_vinculo(vinculo)
    cliente = Cliente(
        codigo=await allocate_codigo_cliente(db),
        nombre_razon_social=vinculo.nombre or f"{cliente_padre.nombre_razon_social} ({vinculo.rol})",
        tipo_persona=vinculo.tipo_persona,
        cif_nif=cif_nif,
        dni_nie=dni_nie,
        matriculas=[],
        telefono=vinculo.telefono,
        email=vinculo.email,
        sancion_origen_id=None,
        vinculo_origen_id=vinculo.id,
    )
    db.add(cliente)
    await db.flush()

    vinculo.cliente_vinculado_id = cliente.id

    identificador_padre = cliente_padre.cif_nif or cliente_padre.dni_nie
    db.add(VinculoCliente(
        cliente_id=cliente.id, cliente_vinculado_id=cliente_padre.id, rol=_rol_reciproco(vinculo.rol),
        nombre=cliente_padre.nombre_razon_social, tipo_persona=cliente_padre.tipo_persona,
        identificador=identificador_padre,
        tipo_identificador="CIF" if cliente_padre.cif_nif else ("DNI" if cliente_padre.dni_nie else None),
        telefono=cliente_padre.telefono, email=cliente_padre.email,
    ))

    movidas = await db.execute(
        update(Sancionado)
        .where(Sancionado.cliente_id == cliente_padre.id, Sancionado.vinculo_id == vinculo.id)
        .values(cliente_id=cliente.id, vinculo_id=None, estado_oportunidad="cliente")
    )
    await db.execute(
        update(Notificacion)
        .where(Notificacion.sancionado_id.in_(select(Sancionado.id).where(Sancionado.cliente_id == cliente.id)))
        .values(cliente_id=cliente.id)
    )

    db.add(ActividadCliente(
        cliente_id=cliente.id, tipo="conversion", titulo="Conversión desde vínculo",
        detalle=f"Creado a partir del vínculo «{vinculo.rol}» de {cliente_padre.nombre_razon_social} ({cliente_padre.codigo})",
        datos={
            "cliente_padre_id": cliente_padre.id, "vinculo_id": vinculo.id,
            "sanciones_movidas": int(movidas.rowcount or 0),
        },
    ))
    db.add(ActividadCliente(
        cliente_id=cliente_padre.id, tipo="sistema",
        titulo=f"Vínculo convertido en cliente: {cliente.nombre_razon_social} ({cliente.codigo})",
        datos={"cliente_id": cliente.id, "vinculo_id": vinculo.id},
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


async def eliminar_cliente(db: AsyncSession, cliente: Cliente) -> dict[str, int]:
    """Delete a client and everything that hangs off it, leaving the rest of
    the system consistent:

    - its notices go back to being plain opportunities (``revisada``) — they
      are BOE publications, not the client's own data;
    - alerts, and other clients' links to it, lose the reference;
    - notes, activity, agenda, vínculos, history results and contracts go
      with it (the PDFs of the contracts too).

    Refuses (``ClienteConFacturas``) when it has issued invoices."""
    facturas = (await db.execute(
        select(func.count(DocumentoComercial.id)).where(
            DocumentoComercial.cliente_id == cliente.id, DocumentoComercial.tipo == "factura"
        )
    )).scalar_one()
    if facturas:
        raise ClienteConFacturas(int(facturas))

    resumen: dict[str, int] = {}
    liberadas = await db.execute(
        update(Sancionado).where(Sancionado.cliente_id == cliente.id, Sancionado.estado_oportunidad == "cliente")
        .values(estado_oportunidad="revisada")
    )
    resumen["sanciones_liberadas"] = int(liberadas.rowcount or 0)
    await db.execute(update(Sancionado).where(Sancionado.cliente_id == cliente.id).values(cliente_id=None, vinculo_id=None))
    await db.execute(update(Notificacion).where(Notificacion.cliente_id == cliente.id).values(cliente_id=None))

    # Other clients' vínculos that pointed at this ficha keep the person, as a
    # plain linked entity (a vínculo needs a name or a ficha).
    for vinculo in (await db.execute(
        select(VinculoCliente).where(VinculoCliente.cliente_vinculado_id == cliente.id)
    )).scalars().all():
        vinculo.cliente_vinculado_id = None
        vinculo.nombre = vinculo.nombre or cliente.nombre_razon_social
        vinculo.identificador = vinculo.identificador or cliente.cif_nif or cliente.dni_nie

    rutas = [
        ruta for ruta in (await db.execute(
            select(DocumentoComercial.pdf_path).where(DocumentoComercial.cliente_id == cliente.id)
        )).scalars().all() if ruta
    ]
    for tabla in (AccionAgendada, ActividadCliente, NotaCliente):
        await db.execute(delete(tabla).where(tabla.cliente_id == cliente.id))
    await db.execute(delete(VinculoCliente).where(VinculoCliente.cliente_id == cliente.id))
    await db.execute(delete(Cliente).where(Cliente.id == cliente.id))
    await db.flush()

    for ruta in rutas:
        try:
            os.remove(ruta)
        except OSError:
            logger.warning("No se pudo borrar el fichero %s del cliente eliminado", ruta)
    return resumen
