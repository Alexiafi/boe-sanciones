"""Remove contact data that belongs to the issuing administration.

Until this revision the contact "enrichment" harvested phones and emails from
the text of the BOE/TEU notice itself (and the structured extraction could copy
the office's own line into the opportunity). Those values are the
*Administration's* — never the sanctioned party's — so every opportunity that
carries one is reset to "pendiente" and can be enriched again (now from the web
only). Values a person typed by hand (``contacto_estado = 'manual'``) are never
touched.

Evidence on a real database (17,000 opportunities): 1,481 had a phone, and
the same few numbers — a DGT desk, a municipal office — were attached to
hundreds of different people. Even the phones that appeared once belonged to
"Ayuntamiento de Reinosa" or "Servicio de Ferias y Mercados": the structured
extraction copied the issuer's line, never the sanctioned party's. So the rules,
applied to non-manual rows only, are:

1. a phone/email with **no provenance** — it was not found by the enrichment
   (which records where each value came from) — came out of the notice text:
   removed;
2. contact found through the notice text (``contacto_fuente`` in boe/teu/
   historico, or copied from a sibling row that was): removed;
3. phone/email that is a public-body number/domain (012, 060, ``…gob.es``,
   ``ayuntamiento…``), a "phone" that is not a 9-digit number, or a tracking
   address (``…sentry.io``): removed even when it has provenance;
4. a phone/email repeated across three or more different identifiers (a
   notice's own contact line shows up on every party it lists): removed even
   when it has provenance.

Self-contained on purpose (no imports from ``app``): a migration must keep
working after the application code it was written against changes.

Revision ID: 0016_limpia_contacto_organismo
Revises: 0015_identidad_y_estados
Create Date: 2026-10-01
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "0016_limpia_contacto_organismo"
down_revision = "0015_identidad_y_estados"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_FUENTES_DEL_TEXTO = {"boe", "teu", "historico", "sancionado"}
_DOMINIOS = (
    "gob.es", "boe.es", "dgt.es", "aeat.es", "seg-social.es", "gencat.cat", "gva.es", "madrid.org",
    "comunidad.madrid", "juntadeandalucia.es", "xunta.gal", "euskadi.eus", "euskadi.net", "navarra.es",
    "jcyl.es", "jccm.es", "carm.es", "caib.es", "gobiernodecanarias.org", "larioja.org", "aragon.es",
    "asturias.es", "cantabria.es", "juntaex.es", "bizkaia.eus", "bizkaia.net", "gipuzkoa.eus",
    "gipuzkoa.net", "araba.eus", "bcn.cat", "aoc.cat", "poderjudicial.es",
)
_FRAGMENTOS = ("ayuntamiento", "ayto", "diputacion", "deputacion", "ajuntament", "concello")
_NUMEROS_CORTOS = {"010", "012", "016", "060", "061", "062", "080", "085", "088", "091", "092", "112"}
_PREFIJOS = ("800", "900", "901", "902", "905")
_REPETIDO_EN = 3  # distinct identifiers sharing one phone/email


def _digitos(valor: str) -> str:
    d = re.sub(r"\D", "", valor)
    if d.startswith("0034"):
        d = d[4:]
    elif d.startswith("34") and len(d) >= 11:
        d = d[2:]
    return d


def _telefono_institucional(valor: str | None) -> bool:
    if not valor:
        return False
    d = _digitos(valor)
    return d in _NUMEROS_CORTOS or (len(d) == 9 and d[:3] in _PREFIJOS)


def _telefono_invalido(valor: str | None) -> bool:
    """Older enrichment runs stored fragments such as ``-8319-33318``."""
    return bool(valor) and not re.fullmatch(r"[6-9]\d{8}", _digitos(valor))


def _email_institucional(valor: str | None) -> bool:
    if not valor or "@" not in valor:
        return False
    dominio = valor.lower().rpartition("@")[2].strip()
    if dominio.endswith("sentry.io"):
        return True
    if any(dominio == base or dominio.endswith("." + base) for base in _DOMINIOS):
        return True
    return any(fragmento in dominio for fragmento in _FRAGMENTOS)


def _clave(campo: str, valor: str | None) -> str | None:
    if not valor:
        return None
    return (_digitos(valor) or None) if campo == "telefono" else (valor.strip().lower() or None)


_REDES = ("linkedin_url", "facebook_url", "instagram_url", "twitter_url")


def upgrade() -> None:
    bind = op.get_bind()
    filas = bind.execute(
        sa.text(
            "SELECT id, identificador, telefono, telefono_secundario, email, web, linkedin_url, facebook_url, "
            "instagram_url, twitter_url, contacto_estado, contacto_fuente, contacto_detalle "
            "FROM sancionados WHERE contacto_estado <> 'manual' "
            "AND (telefono IS NOT NULL OR email IS NOT NULL OR telefono_secundario IS NOT NULL "
            "     OR contacto_estado = 'encontrado')"
        )
    ).mappings().all()

    # How many different parties carry each phone/email (rule 3).
    titulares: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fila in filas:
        titular = (fila["identificador"] or f"id:{fila['id']}").strip().upper()
        for campo in ("telefono", "email"):
            clave = _clave(campo, fila[campo])
            if clave:
                titulares[(campo, clave)].add(titular)

    limpiadas = 0
    for fila in filas:
        cambios: dict[str, object] = {}
        detalle = dict(fila["contacto_detalle"] or {})
        del_texto = fila["contacto_estado"] == "encontrado" and fila["contacto_fuente"] in _FUENTES_DEL_TEXTO

        # Found by the web enrichment (it records where each value came from).
        encontrado_en_la_web = fila["contacto_estado"] == "encontrado" and not del_texto

        for campo in ("telefono", "telefono_secundario", "email"):
            valor = fila[campo]
            if not valor:
                continue
            base = "telefono" if campo.startswith("telefono") else "email"
            institucional = (
                _telefono_institucional(valor) or _telefono_invalido(valor) if base == "telefono" else _email_institucional(valor)
            )
            repetido = len(titulares.get((base, _clave(base, valor) or ""), ())) >= _REPETIDO_EN
            con_origen = (detalle.get(campo) or {}).get("valor") == valor or encontrado_en_la_web
            if del_texto or not con_origen or institucional or repetido:
                cambios[campo] = None
                detalle.pop(campo, None)
        if del_texto:
            # The web/social links of a text-harvested row never came from it,
            # but the provenance recorded for them did: keep them only if the
            # provenance entry points at a real URL.
            for campo in ("web",) + _REDES:
                dato = detalle.get(campo)
                if dato and not str(dato.get("fuente_url") or "").startswith("http"):
                    cambios[campo] = None
                    detalle.pop(campo, None)

        if not cambios:
            continue

        resultante = {
            campo: (cambios[campo] if campo in cambios else fila[campo])
            for campo in ("telefono", "telefono_secundario", "email", "web") + _REDES
        }
        if not any(resultante.values()) and fila["contacto_estado"] == "encontrado":
            # Nothing usable left: back to "pendiente" so it can be enriched again.
            cambios.update(
                contacto_estado="pendiente", contacto_fuente=None, contacto_url=None,
                contacto_confidence=None, contacto_actualizado_at=None,
            )
            detalle = {}

        sets = [f"{campo} = :{campo}" for campo in cambios]
        parametros = dict(cambios)
        parametros["id"] = fila["id"]
        if detalle != dict(fila["contacto_detalle"] or {}):
            sets.append("contacto_detalle = CAST(:detalle AS jsonb)")
            parametros["detalle"] = json.dumps(detalle) if detalle else None
        bind.execute(sa.text(f"UPDATE sancionados SET {', '.join(sets)} WHERE id = :id"), parametros)
        limpiadas += 1

    logger.info("Contacto del organismo eliminado en %d oportunidades", limpiadas)


def downgrade() -> None:
    # Irreversible by design: the removed values were wrong (the notice
    # issuer's own contact data), so there is nothing worth restoring.
    pass
