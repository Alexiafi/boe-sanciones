"""Remove contact data that belongs to a company directory, not to the party.

Until this revision the web enrichment took any phone/email/website/social link
on a page that mentioned the party's CIF. On directory record pages (iberinform,
qdq, einforma…) that is the DIRECTORY's own customer line, mailbox, website and
social accounts: the client reported Grupo Boheme Sensations stored with
"900 213 215 / atencionclientes@iberinform.es / www.iberinform.es / LinkedIn
iberinform", and Moldes Diaz with qdq.com and QDQ's Facebook/Instagram/X.

Applied to non-manual rows only (``contacto_estado <> 'manual'`` — what a person
typed is never touched):

1. a website on a directory/aggregator domain: removed;
2. a social profile, email or website whose recorded source (``contacto_detalle``)
   is a directory page and that points to that directory itself (its domain or
   its handle): removed;
3. a public-service / freephone number (900, 901, 902, 905, 800, 012…): removed;
4. a phone or email carried by three or more different parties: removed.

A row left without phone or email goes back to ``pendiente`` so the new
enrichment can search it again. Self-contained on purpose (no imports from
``app``).

Revision ID: 0018_limpia_contacto_directorios
Revises: 0017_contrato_octubre
Create Date: 2026-10-17
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from urllib.parse import urlparse

from alembic import op
import sqlalchemy as sa

revision = "0018_limpia_contacto_directorios"
down_revision = "0017_contrato_octubre"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_DIRECTORIOS = (
    "dnb.com", "verif.com", "infoempresa.com", "eleconomista.es", "einforma.com", "axesor.es", "datoscif.es",
    "paginasamarillas.es", "elpais.com", "interempresas.net", "nextdoor.com", "empresia.es", "infocif.es",
    "registro-mercantil.com", "iberinform.es", "librebor.me", "universia.es", "cylex.es", "infobel.com",
    "kompass.com", "europages.es", "europages.com", "expansion.com", "11870.com", "qdq.com", "hotfrog.es",
    "opencorporates.com", "dateas.com", "sociedad.info", "infonif.es", "economia3.com", "informa.es",
    "ocu.org", "boe.es", "significadode.org", "wordmeaning.org", "abebooks.com", "finect.com", "investing.com",
    "cnmv.es", "apiempresas.es", "xared.com", "lasprovincias.es",
)
_NUMEROS_CORTOS = {"010", "012", "016", "060", "061", "062", "080", "085", "088", "091", "092", "112"}
_PREFIJOS = ("800", "900", "901", "902", "905")
_REPETIDO_EN = 3
_REDES = ("linkedin_url", "facebook_url", "instagram_url", "twitter_url")


def _dominio(url: str | None) -> str:
    if not url:
        return ""
    if "@" in url and "://" not in url:
        dominio = url.rpartition("@")[2]
    else:
        dominio = urlparse(url if "://" in url else f"https://{url}").netloc
    dominio = dominio.lower().strip()
    return dominio[4:] if dominio.startswith("www.") else dominio


def _es_directorio(dominio: str) -> bool:
    return any(dominio == d or dominio.endswith("." + d) for d in _DIRECTORIOS)


def _marca(dominio: str) -> str:
    """'iberinform' for iberinform.es, 'qdq' for qdq.com."""
    partes = dominio.split(".")
    return partes[-2] if len(partes) >= 2 else dominio


def _digitos(valor: str) -> str:
    d = re.sub(r"\D", "", valor)
    if d.startswith("0034"):
        d = d[4:]
    elif d.startswith("34") and len(d) >= 11:
        d = d[2:]
    return d


def _telefono_publico(valor: str | None) -> bool:
    if not valor:
        return False
    d = _digitos(valor)
    return d in _NUMEROS_CORTOS or (len(d) == 9 and d[:3] in _PREFIJOS)


def _clave(campo: str, valor: str | None) -> str | None:
    if not valor:
        return None
    return (_digitos(valor)[-9:] or None) if campo.startswith("telefono") else (valor.strip().lower() or None)


def _apunta_al_directorio(valor: str, fuente: str) -> bool:
    """The value is the directory's own (its domain, or its handle on a social network)."""
    dominio_fuente = _dominio(fuente)
    if not _es_directorio(dominio_fuente):
        return False
    marca = _marca(dominio_fuente)
    dominio_valor = _dominio(valor)
    if dominio_valor == dominio_fuente or dominio_valor.endswith("." + dominio_fuente):
        return True
    handle = valor.rstrip("/").rsplit("/", 1)[-1].lower()
    return len(marca) >= 3 and marca in handle


def upgrade() -> None:
    bind = op.get_bind()
    filas = bind.execute(
        sa.text(
            "SELECT id, identidad_clave, identificador, telefono, telefono_secundario, email, web, linkedin_url, "
            "facebook_url, instagram_url, twitter_url, contacto_estado, contacto_detalle "
            "FROM sancionados WHERE contacto_estado <> 'manual' "
            "AND (telefono IS NOT NULL OR telefono_secundario IS NOT NULL OR email IS NOT NULL OR web IS NOT NULL "
            "     OR linkedin_url IS NOT NULL OR facebook_url IS NOT NULL OR instagram_url IS NOT NULL "
            "     OR twitter_url IS NOT NULL)"
        )
    ).mappings().all()

    titulares: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fila in filas:
        titular = (fila["identidad_clave"] or fila["identificador"] or f"id:{fila['id']}").strip().upper()
        for campo in ("telefono", "telefono_secundario", "email"):
            clave = _clave(campo, fila[campo])
            if clave:
                titulares[("telefono" if campo.startswith("telefono") else "email", clave)].add(titular)

    limpiadas = 0
    for fila in filas:
        detalle = dict(fila["contacto_detalle"] or {})
        cambios: dict[str, object] = {}

        def quitar(campo: str) -> None:
            cambios[campo] = None
            detalle.pop(campo, None)

        if fila["web"] and _es_directorio(_dominio(fila["web"])):
            quitar("web")
        for campo in ("email", "web", *_REDES):
            valor = fila[campo]
            fuente = (detalle.get(campo) or {}).get("fuente_url")
            if valor and campo not in cambios and fuente and _apunta_al_directorio(valor, fuente):
                quitar(campo)
        if fila["email"] and "email" not in cambios and _es_directorio(_dominio(fila["email"])):
            quitar("email")
        for campo in ("telefono", "telefono_secundario"):
            valor = fila[campo]
            if valor and (_telefono_publico(valor) or len(titulares.get(("telefono", _clave(campo, valor) or ""), ())) >= _REPETIDO_EN):
                quitar(campo)
        if fila["email"] and "email" not in cambios:
            if len(titulares.get(("email", _clave("email", fila["email"]) or ""), ())) >= _REPETIDO_EN:
                quitar("email")

        if not cambios:
            continue
        queda_contacto = any(
            fila[c] and c not in cambios for c in ("telefono", "telefono_secundario", "email")
        )
        sets = [f"{campo} = NULL" for campo in cambios]
        params: dict[str, object] = {"id": fila["id"]}
        sets.append("contacto_detalle = CAST(:detalle AS JSONB)")
        params["detalle"] = json.dumps(detalle) if detalle else None
        if not queda_contacto and fila["contacto_estado"] in ("encontrado", "no_encontrado", "sin_datos"):
            sets += ["contacto_estado = 'pendiente'", "contacto_fuente = NULL", "contacto_url = NULL",
                     "contacto_confidence = NULL", "contacto_actualizado_at = NULL"]
        bind.execute(sa.text(f"UPDATE sancionados SET {', '.join(sets)} WHERE id = :id"), params)
        limpiadas += 1

    logger.info("0018: %s oportunidades con contacto de directorios/organismos limpiadas", limpiadas)


def downgrade() -> None:
    # Data cleanup: the removed values were not the parties' own. Nothing to restore.
    pass
