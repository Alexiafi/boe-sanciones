"""One person, one record: identity resolution across notifications.

The BOE/TEU publish a new notice every time a person or company is fined, and
the TEU identifies them by DNI/NIF/CIF alone. Without this module each notice
was an island: a client reappeared as a bare CIF, a contact already found (or a
call already made) was invisible on the next notice, and data typed on one
notification was missing on the others.

Two opportunities (or an opportunity and a client) are the same party when
their ``identidad_clave`` — the normalised, *complete* document number — is
equal. This module:

- on arrival of a new opportunity (``ResolverIdentidad``): attaches it to the
  client that already owns that number and inherits the name/contact data
  already known, so the first thing Judit sees is "this is client X";
- on a manual edit (``propagar_edicion_*``): shares the edit with every other
  notification of that party and with the client's ficha, in both directions;
- when a client is created or its identifiers change (``vincular_*``): attaches
  every earlier notification of that number to the client;
- for listings (``resumen_identidades``): tells the UI how many other notices
  that party has and whether anyone already worked them.

Masked identifiers (``***1234**``) have no key and are never merged.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.cliente import ActividadCliente, Cliente, VinculoCliente
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.models.seguimiento import Seguimiento
from app.services.historico.patterns import clave_identidad, normalizar_nombre

# Identity/contact fields that describe the *party* (shared across its notices),
# as opposed to the sanction itself (amount, file number, deadlines…).
CAMPOS_PERFIL = (
    "nombre", "tipo_persona", "direccion", "localidad", "provincia", "codigo_postal",
    "telefono", "email", "web", "telefono_secundario",
    "linkedin_url", "facebook_url", "instagram_url", "twitter_url",
)
CAMPOS_CONTACTO = ("telefono", "email", "telefono_secundario", "web",
                   "linkedin_url", "facebook_url", "instagram_url", "twitter_url")
_PROVENIENCIA = (
    "contacto_estado", "contacto_fuente", "contacto_url", "contacto_confidence",
    "contacto_detalle", "contacto_actualizado_at",
)
# Cliente column -> Sancionado column.
CLIENTE_A_SANCIONADO = {
    "nombre_razon_social": "nombre", "tipo_persona": "tipo_persona", "telefono": "telefono",
    "email": "email", "web": "web", "direccion_fiscal": "direccion", "localidad": "localidad",
    "provincia": "provincia", "codigo_postal": "codigo_postal",
}
SANCIONADO_A_CLIENTE = {v: k for k, v in CLIENTE_A_SANCIONADO.items() if v != "nombre"}
MAX_HERMANAS = 10
# A state set on one notice that is also the answer for the party's other open notices.
ESTADOS_QUE_SE_PROPAGAN = ("contactada", "descartada")
ESTADOS_ABIERTOS = ("nueva", "revisada")


def _vacio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _nombre_vacio(sancionado: Sancionado) -> bool:
    nombre = (sancionado.nombre or "").strip()
    if not nombre:
        return True
    return bool(sancionado.identificador) and nombre.upper() == sancionado.identificador.strip().upper()


# Same accent/punctuation folding as ``patterns.normalizar_nombre``, in SQL.
_ACENTOS = "ÁÉÍÓÚÜÀÈÌÒÙÂÊÎÔÛÄËÏÖÑÇ"
_SIN_ACENTOS = "AEIOUUAEIOUAEIOUAEIOUNC"


def _nombre_sql(columna):
    return func.translate(func.translate(func.upper(columna), _ACENTOS, _SIN_ACENTOS), ".,", "")


_FORMA_SOCIETARIA_RE = re.compile(r"\b(SL|SLU|SLL|SA|SAU|SC|SCP|CB|AIE|UTE|SCOOP)$")


def nombre_clave(nombre: str | None) -> str | None:
    """Normalised name usable to recognise a CLIENT that has no document
    number on file: only names distinctive enough not to be homonyms — a
    company (legal form) or a person with at least three name words."""
    normalizado = normalizar_nombre(nombre)
    if len(normalizado) < 8:
        return None
    if _FORMA_SOCIETARIA_RE.search(normalizado) or len(normalizado.split()) >= 3:
        return normalizado
    return None


def claves_de_cliente(cliente: Cliente) -> list[str]:
    return [clave for clave in (clave_identidad(cliente.cif_nif), clave_identidad(cliente.dni_nie)) if clave]


# --------------------------------------------------------------------------
# Arrival of a new opportunity (sync: Celery pipeline)
# --------------------------------------------------------------------------

def heredar_perfil(
    db: Session, sancionado: Sancionado, *, cliente: Cliente | None = None, vinculo: VinculoCliente | None = None,
) -> int:
    """Fill the blanks of ``sancionado`` from what is already known about the
    same party: the client's ficha (or the vínculo's) first, then its other
    notices. Never overwrites a value. Returns how many fields were filled."""
    clave = clave_identidad(sancionado.identificador)
    if not clave:
        return 0
    rellenados = 0

    def poner(campo: str, valor: Any) -> None:
        nonlocal rellenados
        if campo == "nombre":
            vacio = _nombre_vacio(sancionado)
            # The extraction sometimes writes the DNI/CIF itself in the name field.
            if isinstance(valor, str) and valor.strip().upper() == (sancionado.identificador or "").strip().upper():
                return
        else:
            vacio = _vacio(getattr(sancionado, campo))
        if vacio and not _vacio(valor):
            setattr(sancionado, campo, valor)
            rellenados += 1

    if vinculo is not None:
        poner("nombre", vinculo.nombre)
        poner("tipo_persona", vinculo.tipo_persona)
        poner("telefono", vinculo.telefono)
        poner("email", vinculo.email)
    elif cliente is not None:
        for campo_cliente, campo in CLIENTE_A_SANCIONADO.items():
            poner(campo, getattr(cliente, campo_cliente))

    hermanas = db.execute(
        select(Sancionado)
        .where(Sancionado.identidad_clave == clave, Sancionado.id != sancionado.id)
        .order_by(Sancionado.id.desc())
        .limit(MAX_HERMANAS)
    ).scalars().all()
    contacto_heredado_de: Sancionado | None = None
    for hermana in hermanas:
        for campo in CAMPOS_PERFIL:
            antes = getattr(sancionado, campo)
            poner(campo, getattr(hermana, campo))
            if campo in CAMPOS_CONTACTO and _vacio(antes) and not _vacio(getattr(sancionado, campo)):
                contacto_heredado_de = contacto_heredado_de or hermana
    # The provenance ("encontrado en…", "manual") travels with the contact it
    # describes; a "no encontrado" sibling also spares a paid search for the
    # same person.
    if sancionado.contacto_estado == "pendiente":
        origen = contacto_heredado_de or next(
            (h for h in hermanas if h.contacto_estado in ("no_encontrado", "sin_datos")), None
        )
        if origen is not None:
            for campo in _PROVENIENCIA:
                setattr(sancionado, campo, getattr(origen, campo))
    return rellenados


def heredar_perfil_sin_clave(sancionado: Sancionado, cliente: Cliente) -> None:
    """Fill blanks from the client ficha (for notices matched by name)."""
    for campo_cliente, campo in CLIENTE_A_SANCIONADO.items():
        if campo == "nombre":
            continue
        if _vacio(getattr(sancionado, campo)) and not _vacio(getattr(cliente, campo_cliente)):
            setattr(sancionado, campo, getattr(cliente, campo_cliente))


def compartir_perfil(db: Session, sancionado: Sancionado) -> int:
    """Give the party's other notices (and its client ficha) the data this
    notice has just gained — e.g. a phone number found on the web — wherever
    they still have a blank. Never overwrites. Returns how many records changed."""
    clave = clave_identidad(sancionado.identificador)
    if not clave:
        return 0
    cambiados = 0
    hermanas = db.execute(
        select(Sancionado).where(Sancionado.identidad_clave == clave, Sancionado.id != sancionado.id)
    ).scalars().all()
    for hermana in hermanas:
        tocada = False
        recibio_contacto = False
        for campo in CAMPOS_PERFIL:
            if campo == "nombre":
                continue  # handled below: only a real name, never a DNI written in the name field
            valor = getattr(sancionado, campo)
            if _vacio(getattr(hermana, campo)) and not _vacio(valor):
                setattr(hermana, campo, valor)
                tocada = True
                recibio_contacto = recibio_contacto or campo in CAMPOS_CONTACTO
        if _nombre_vacio(hermana) and not _vacio(sancionado.nombre) and not _nombre_vacio(sancionado):
            hermana.nombre = sancionado.nombre
            tocada = True
        if recibio_contacto and hermana.contacto_estado in ("pendiente", "no_encontrado", "sin_datos"):
            for campo in _PROVENIENCIA:
                setattr(hermana, campo, getattr(sancionado, campo))
        cambiados += int(tocada)

    cliente = db.execute(
        select(Cliente).where(
            (func.regexp_replace(func.upper(Cliente.cif_nif), r"[\s.\-]", "", "g") == clave)
            | (func.regexp_replace(func.upper(Cliente.dni_nie), r"[\s.\-]", "", "g") == clave)
        ).order_by(Cliente.id).limit(1)
    ).scalars().first()
    if cliente is not None:
        for campo_cliente, campo in CLIENTE_A_SANCIONADO.items():
            if campo == "nombre":
                continue
            if _vacio(getattr(cliente, campo_cliente)) and not _vacio(getattr(sancionado, campo)):
                setattr(cliente, campo_cliente, getattr(sancionado, campo))
                cambiados += 1
    return cambiados


class ResolverIdentidad:
    """Per-run resolver: loads the client identifier index once, then each new
    opportunity is resolved with dictionary lookups."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._indice: dict[str, tuple[int, int | None]] | None = None
        self._indice_nombres: dict[str, int] | None = None

    @property
    def indice(self) -> dict[str, tuple[int, int | None]]:
        if self._indice is None:
            from app.services.vinculos import indice_identificadores

            self._indice = indice_identificadores(self.db)
        return self._indice

    @property
    def indice_nombres(self) -> dict[str, int]:
        """Clients WITHOUT any DNI/CIF on file, by distinctive name. Without a
        number their new notices could never be recognised otherwise."""
        if self._indice_nombres is None:
            self._indice_nombres = {}
            for cliente_id, nombre in self.db.execute(
                select(Cliente.id, Cliente.nombre_razon_social).where(
                    (Cliente.cif_nif.is_(None) | (Cliente.cif_nif == "")),
                    (Cliente.dni_nie.is_(None) | (Cliente.dni_nie == "")),
                    Cliente.estado_cliente != "inactivo",
                ).order_by(Cliente.id.desc())
            ).all():
                clave = nombre_clave(nombre)
                if clave:
                    self._indice_nombres[clave] = cliente_id
        return self._indice_nombres

    def __call__(self, sancionado: Sancionado, stats: dict | None = None) -> bool:
        """Returns True when the opportunity was attached to an existing client."""
        from app.services.vinculos import asignar_sancion_a_cliente

        clave = clave_identidad(sancionado.identificador)
        if not clave:
            return self._por_nombre(sancionado, stats)
        sancionado.identidad_clave = clave
        destino = self.indice.get(clave)
        cliente = vinculo = None
        asignada = False
        if destino is not None:
            cliente_id, vinculo_id = destino
            cliente = self.db.get(Cliente, cliente_id)
            vinculo = self.db.get(VinculoCliente, vinculo_id) if vinculo_id is not None else None
            asignada = asignar_sancion_a_cliente(self.db, sancionado, cliente_id, vinculo_id, notificar=False)
            if asignada and stats is not None:
                stats["clientes_asignados"] = int(stats.get("clientes_asignados", 0)) + 1
        heredar_perfil(self.db, sancionado, cliente=None if vinculo else cliente, vinculo=vinculo)
        return asignada

    def _por_nombre(self, sancionado: Sancionado, stats: dict | None) -> bool:
        """A notice with no complete document number (masked DNI, name only)
        is attached to a client without a number when the NAME matches exactly
        and is distinctive. The activity entry says it was matched by name."""
        from app.services.vinculos import asignar_sancion_a_cliente

        clave = nombre_clave(sancionado.nombre)
        cliente_id = self.indice_nombres.get(clave) if clave else None
        if cliente_id is None:
            return False
        asignada = asignar_sancion_a_cliente(
            self.db, sancionado, cliente_id, None, notificar=False, motivo="por coincidencia exacta del nombre (verifícalo)",
        )
        if asignada:
            cliente = self.db.get(Cliente, cliente_id)
            if cliente is not None:
                heredar_perfil_sin_clave(sancionado, cliente)
            if stats is not None:
                stats["clientes_asignados"] = int(stats.get("clientes_asignados", 0)) + 1
        return asignada


# --------------------------------------------------------------------------
# Client created / identifiers changed (async: API)
# --------------------------------------------------------------------------

async def cliente_por_clave(db: AsyncSession, clave: str, *, excluir_id: int | None = None) -> Cliente | None:
    """The client that owns this document number (own CIF/NIF or DNI/NIE)."""
    def normalizada(columna):
        return func.regexp_replace(func.upper(columna), r"[\s.\-]", "", "g")

    consulta = select(Cliente).where((normalizada(Cliente.cif_nif) == clave) | (normalizada(Cliente.dni_nie) == clave))
    if excluir_id is not None:
        consulta = consulta.where(Cliente.id != excluir_id)
    return (await db.execute(consulta.order_by(Cliente.id).limit(1))).scalars().first()


async def vincular_sanciones_a_cliente(db: AsyncSession, cliente: Cliente) -> int:
    """Attach every earlier, still unassigned notice of this client's document
    numbers (and of its vínculos without a ficha of their own). Quiet: no
    per-notice alert, because these are old news — one activity entry says how
    many were linked. Returns the number of notices attached."""
    objetivos: list[tuple[str, int | None]] = [(clave, None) for clave in claves_de_cliente(cliente)]
    vinculos = (await db.execute(
        select(VinculoCliente).where(VinculoCliente.cliente_id == cliente.id, VinculoCliente.cliente_vinculado_id.is_(None))
    )).scalars().all()
    for vinculo in vinculos:
        clave = clave_identidad(vinculo.identificador)
        if clave:
            objetivos.append((clave, vinculo.id))

    total = 0
    for clave, vinculo_id in objetivos:
        ids = list((await db.execute(
            select(Sancionado.id).where(Sancionado.identidad_clave == clave, Sancionado.cliente_id.is_(None))
        )).scalars().all())
        if not ids:
            continue
        await db.execute(
            update(Sancionado).where(Sancionado.id.in_(ids))
            .values(cliente_id=cliente.id, vinculo_id=vinculo_id, estado_oportunidad="cliente")
        )
        await db.execute(
            update(Notificacion).where(Notificacion.sancionado_id.in_(ids), Notificacion.cliente_id.is_(None))
            .values(cliente_id=cliente.id)
        )
        total += len(ids)
    if total:
        db.add(ActividadCliente(
            cliente_id=cliente.id, tipo="sistema",
            titulo=f"{total} sanción(es) anteriores vinculadas por identificador",
            datos={"vinculadas": total},
        ))

    # A client with no DNI/CIF on file can only be recognised by its name:
    # exact and distinctive names only (see ``nombre_clave``).
    clave_nombre = None if claves_de_cliente(cliente) else nombre_clave(cliente.nombre_razon_social)
    if clave_nombre:
        ids = list((await db.execute(
            select(Sancionado.id).where(
                Sancionado.cliente_id.is_(None), Sancionado.identidad_clave.is_(None),
                Sancionado.nombre.is_not(None), _nombre_sql(Sancionado.nombre) == clave_nombre,
            )
        )).scalars().all())
        if ids:
            await db.execute(
                update(Sancionado).where(Sancionado.id.in_(ids))
                .values(cliente_id=cliente.id, vinculo_id=None, estado_oportunidad="cliente")
            )
            await db.execute(
                update(Notificacion).where(Notificacion.sancionado_id.in_(ids), Notificacion.cliente_id.is_(None))
                .values(cliente_id=cliente.id)
            )
            db.add(ActividadCliente(
                cliente_id=cliente.id, tipo="sistema",
                titulo=f"{len(ids)} sanción(es) anteriores vinculadas por coincidencia exacta del nombre (verifícalas)",
                datos={"vinculadas_por_nombre": len(ids)},
            ))
            total += len(ids)
    return total


# --------------------------------------------------------------------------
# Manual edits (async: API)
# --------------------------------------------------------------------------

def _marcar_contacto_manual(sancionado: Sancionado, *, ahora) -> None:
    if sancionado.telefono or sancionado.email:
        sancionado.contacto_estado = "manual"
        sancionado.contacto_fuente = "manual"
        sancionado.contacto_url = None
        sancionado.contacto_confidence = 1.0
        sancionado.contacto_actualizado_at = ahora
    elif sancionado.contacto_estado == "manual":
        sancionado.contacto_estado = "pendiente"
        sancionado.contacto_fuente = None
        sancionado.contacto_url = None
        sancionado.contacto_confidence = None
        sancionado.contacto_actualizado_at = None


async def propagar_edicion_sancionado(
    db: AsyncSession, sancionado: Sancionado, campos: set[str], *, ahora,
) -> dict[str, int]:
    """Share an explicit edit of ``sancionado`` with every other notice of the
    same party and with the client ficha. ``campos`` are the fields the user
    actually sent in the PATCH. Returns counters (for tests/logging)."""
    resultado = {"hermanas": 0, "cliente": 0}
    clave = clave_identidad(sancionado.identificador)
    compartidos = [c for c in campos if c in CAMPOS_PERFIL]
    estado = sancionado.estado_oportunidad if "estado_oportunidad" in campos else None

    if clave:
        hermanas = (await db.execute(
            select(Sancionado).where(Sancionado.identidad_clave == clave, Sancionado.id != sancionado.id)
        )).scalars().all()
        for hermana in hermanas:
            tocada = False
            for campo in compartidos:
                if getattr(hermana, campo) != getattr(sancionado, campo):
                    setattr(hermana, campo, getattr(sancionado, campo))
                    tocada = True
            if tocada and {"telefono", "email"} & set(compartidos):
                _marcar_contacto_manual(hermana, ahora=ahora)
            if estado in ESTADOS_QUE_SE_PROPAGAN and hermana.estado_oportunidad in ESTADOS_ABIERTOS:
                hermana.estado_oportunidad = estado
                tocada = True
            resultado["hermanas"] += int(tocada)

    cliente = await db.get(Cliente, sancionado.cliente_id) if sancionado.cliente_id else None
    if cliente is None and clave:
        cliente = await cliente_por_clave(db, clave)
        if cliente is not None and sancionado.cliente_id is None and sancionado.vinculo_id is None:
            sancionado.cliente_id = cliente.id
            sancionado.estado_oportunidad = "cliente"
    if cliente is not None and sancionado.vinculo_id is None:
        for campo in compartidos:
            campo_cliente = SANCIONADO_A_CLIENTE.get(campo)
            if campo_cliente is None:
                continue
            valor = getattr(sancionado, campo)
            if getattr(cliente, campo_cliente) != valor and not (valor is None and campo_cliente == "tipo_persona"):
                setattr(cliente, campo_cliente, valor)
                resultado["cliente"] += 1
        if "nombre" in compartidos and sancionado.nombre and (
            cliente.nombre_razon_social.startswith("Oportunidad ")
            or clave_identidad(cliente.nombre_razon_social)
        ):
            cliente.nombre_razon_social = sancionado.nombre
            resultado["cliente"] += 1
    return resultado


async def propagar_edicion_cliente(db: AsyncSession, cliente: Cliente, campos: set[str], *, ahora) -> int:
    """Share an edit of the client ficha with the notices that belong to the
    client itself (not those tagged to one of its vínculos)."""
    mapa = {c: s for c, s in CLIENTE_A_SANCIONADO.items() if c in campos}
    claves = claves_de_cliente(cliente)
    if not mapa:
        return 0
    condicion = (Sancionado.cliente_id == cliente.id) & Sancionado.vinculo_id.is_(None)
    if claves:
        condicion = condicion | (Sancionado.identidad_clave.in_(claves) & Sancionado.vinculo_id.is_(None))
    filas = (await db.execute(select(Sancionado).where(condicion))).scalars().all()
    for fila in filas:
        for campo_cliente, campo in mapa.items():
            setattr(fila, campo, getattr(cliente, campo_cliente))
        if {"telefono", "email"} & set(mapa):
            _marcar_contacto_manual(fila, ahora=ahora)
    return len(filas)


# --------------------------------------------------------------------------
# Read model for listings (async: API)
# --------------------------------------------------------------------------

async def resumen_identidades(db: AsyncSession, claves: set[str]) -> dict[str, dict[str, Any]]:
    """Per party key: how many notices it has, how many were already worked
    and when the last management happened."""
    if not claves:
        return {}
    filas = (await db.execute(
        select(
            Sancionado.identidad_clave,
            func.count(Sancionado.id),
            func.count(Sancionado.id).filter(Sancionado.estado_oportunidad == "contactada"),
            func.max(Sancionado.updated_at).filter(Sancionado.estado_oportunidad == "contactada"),
        ).where(Sancionado.identidad_clave.in_(claves)).group_by(Sancionado.identidad_clave)
    )).all()
    notas = {
        clave: (cuantas, ultima)
        for clave, cuantas, ultima in (await db.execute(
            select(Sancionado.identidad_clave, func.count(Seguimiento.id), func.max(Seguimiento.created_at))
            .join(Seguimiento, Seguimiento.sancionado_id == Sancionado.id)
            .where(Sancionado.identidad_clave.in_(claves)).group_by(Sancionado.identidad_clave)
        )).all()
    }
    resumen: dict[str, dict[str, Any]] = {}
    for clave, total, contactadas, ultimo_contacto in filas:
        cuantas_notas, ultima_nota = notas.get(clave, (0, None))
        candidatos = [f for f in (ultimo_contacto, ultima_nota) if f is not None]
        resumen[clave] = {
            "notificaciones": int(total), "contactadas": int(contactadas),
            "notas": int(cuantas_notas), "ultima_gestion": max(candidatos) if candidatos else None,
        }
    return resumen
