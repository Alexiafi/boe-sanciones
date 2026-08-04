"""Client identifier index and automatic sanction assignment (session 4 —
vínculos y alertas de clientes).

Synchronous, like ``services/oportunidades.py``: this is called from the
Celery daily pipeline (``SyncSessionLocal``), never from the async API router.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cliente import ActividadCliente, Cliente, VinculoCliente
from app.models.sancionado import Sancionado
from app.services.historico.patterns import normalizar_identificador
from app.services.notifier import create_inapp_notification


def indice_identificadores(db: Session) -> dict[str, tuple[int, int | None]]:
    """Map every known identifier (a client's own, or one of their vínculos')
    to ``(cliente_id, vinculo_id)`` — ``vinculo_id`` is ``None`` when the
    identifier belongs to the client itself.

    Built once per scraping run (see ``tasks/scraping.py``) so matching each
    newly extracted sanction costs a dict lookup, not a query per sanction.
    """
    indice: dict[str, tuple[int, int | None]] = {}
    for cliente_id, cif_nif, dni_nie in db.execute(select(Cliente.id, Cliente.cif_nif, Cliente.dni_nie)).all():
        for value in (cif_nif, dni_nie):
            normalizado = normalizar_identificador(value)
            if normalizado:
                indice[normalizado] = (cliente_id, None)

    for vinculo_id, cliente_id, identificador in db.execute(
        select(VinculoCliente.id, VinculoCliente.cliente_id, VinculoCliente.identificador)
    ).all():
        normalizado = normalizar_identificador(identificador)
        if normalizado:
            indice[normalizado] = (cliente_id, vinculo_id)

    return indice


def asignar_sancion_a_cliente(
    db: Session, sancionado: Sancionado, cliente_id: int, vinculo_id: int | None
) -> bool:
    """Attach an opportunity's sanction to an existing client account.

    Idempotent: a sancionado already linked to a client (whether by this same
    path on a replay, or by the manual conversion in
    ``services/clientes.convertir_oportunidad``) is left untouched, so this
    never moves an existing link or duplicates the notification/actividad.
    """
    if sancionado.cliente_id is not None:
        return False

    sancionado.cliente_id = cliente_id
    sancionado.vinculo_id = vinculo_id
    # Mirrors services/clientes.convertir_oportunidad: "cliente" means this
    # opportunity now belongs to a client account, regardless of which of the
    # two code paths got it there.
    sancionado.estado_oportunidad = "cliente"

    titular = None
    if vinculo_id is not None:
        vinculo = db.get(VinculoCliente, vinculo_id)
        titular = vinculo.nombre if vinculo else None

    db.add(ActividadCliente(
        cliente_id=cliente_id, tipo="sistema",
        titulo=f"Nueva sanción detectada{f' ({titular})' if titular else ''}",
        detalle=f"Sanción {sancionado.codigo} asignada automáticamente por coincidencia de identificador.",
        datos={"sancionado_id": sancionado.id, "vinculo_id": vinculo_id},
    ))
    create_inapp_notification(
        db, sancionado, tipo="nueva_sancion_cliente", cliente_id=cliente_id, vinculo_id=vinculo_id,
    )
    return True


def vinculos_de_cliente(db: Session, cliente_id: int) -> list[VinculoCliente]:
    return list(
        db.execute(
            select(VinculoCliente).where(VinculoCliente.cliente_id == cliente_id).order_by(VinculoCliente.id)
        ).scalars().all()
    )
