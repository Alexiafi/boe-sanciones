"""Predicates that recognise the Administration's own contact data.

A BOE/TEU notice is written *by* an administration: the only phone number or
email in it is the issuing office's ("Atención al ciudadano 012",
"recaudacion@diputacion…"), never the sanctioned person's. The extraction no
longer persists phones/emails at all (see ``services/oportunidades``), but a
value can still reach a record from a sibling notice or an old row, so the
enrichment checks anything it is about to reuse against these.
"""

from __future__ import annotations

import re

# Email domains (suffix match) that belong to public bodies. Deliberately a
# list of well-known suffixes, not a guess from the text: a false positive only
# costs a missing email, a false negative costs a wrong person being called.
_DOMINIOS_INSTITUCIONALES = (
    "gob.es", "boe.es", "dgt.es", "aeat.es", "seg-social.es", "mjusticia.es", "mpr.es",
    "gencat.cat", "gva.es", "madrid.org", "comunidad.madrid", "juntadeandalucia.es", "xunta.gal",
    "euskadi.eus", "euskadi.net", "navarra.es", "jcyl.es", "jccm.es", "carm.es", "caib.es",
    "gobiernodecanarias.org", "larioja.org", "aragon.es", "asturias.es", "cantabria.es",
    "juntaex.es", "bizkaia.eus", "bizkaia.net", "gipuzkoa.eus", "gipuzkoa.net", "araba.eus",
    "diba.cat", "ddgi.cat", "diputaciodetarragona.cat", "dipta.cat", "dipucadiz.es",
    "diputacionalicante.es", "dipualba.es", "dipgra.es", "dipsevilla.es", "dipmalaga.es",
    "bcn.cat", "aoc.cat", "poderjudicial.es", "tribunalconstitucional.es",
)
_FRAGMENTOS_INSTITUCIONALES = ("ayuntamiento", "ayto", "diputacion", "deputacion", "ajuntament", "concello")

# Numbers no private party publishes as its own: short public-service numbers
# and the shared-cost / freephone ranges administrations use for attention lines.
_PREFIJOS_INSTITUCIONALES = ("800", "900", "901", "902", "905")
_NUMEROS_CORTOS = {"010", "012", "016", "060", "061", "062", "080", "085", "088", "091", "092", "112"}


def _solo_digitos(valor: str) -> str:
    digitos = re.sub(r"\D", "", valor)
    if digitos.startswith("0034"):
        digitos = digitos[4:]
    elif digitos.startswith("34") and len(digitos) >= 11:
        digitos = digitos[2:]
    return digitos


def es_telefono_institucional(valor: str | None) -> bool:
    if not valor:
        return False
    digitos = _solo_digitos(valor)
    if not digitos:
        return False
    return digitos in _NUMEROS_CORTOS or (len(digitos) == 9 and digitos[:3] in _PREFIJOS_INSTITUCIONALES)


# Extra label prefixes for WEB pages (not mailboxes): official gazettes and
# notice boards that list people by DNI along with the issuing office's own contact.
_ETIQUETAS_DE_PAGINA = ("boletin", "tablon", "bop", "sedeelectronica")


def _etiquetas(dominio: str) -> list[str]:
    return [etiqueta for etiqueta in re.split(r"[.\-]", dominio) if etiqueta]


def es_dominio_institucional(dominio: str | None, *, pagina: bool = False) -> bool:
    """A public body's domain. With ``pagina=True`` also official gazettes and
    notice boards: a page there that mentions a DNI is the *notice*, so any
    phone/email on it is the office's, never the person's.

    Fragments are matched against the START of a domain label (``ayuntamiento-
    de-leon``, ``aytomadrid``), never anywhere inside it: ``hayton.com`` is a
    company."""
    if not dominio:
        return False
    dominio = dominio.lower().strip()
    if dominio.startswith("www."):
        dominio = dominio[4:]
    if any(dominio == base or dominio.endswith("." + base) for base in _DOMINIOS_INSTITUCIONALES):
        return True
    etiquetas = _etiquetas(dominio)
    if any(etiqueta.startswith(fragmento) for etiqueta in etiquetas for fragmento in _FRAGMENTOS_INSTITUCIONALES):
        return True
    if pagina:
        return "sede" in etiquetas or any(
            etiqueta.startswith(prefijo) for etiqueta in etiquetas for prefijo in _ETIQUETAS_DE_PAGINA
        )
    return False


def es_email_institucional(valor: str | None) -> bool:
    if not valor or "@" not in valor:
        return False
    return es_dominio_institucional(valor.rpartition("@")[2])
