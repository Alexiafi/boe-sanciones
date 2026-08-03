"""Regex-only extraction of identifiers/plates/names from BOE plain text.

Pure functions: no I/O, no database, no LLM. This is what keeps the
historical index free — see ``app/tasks/historico_backfill.py``, which is the
only caller during indexing, and never imports ``app.services.extractor``.

Deliberately conservative, same principle as ``enrichment/patterns.py``: a
false positive here silently attaches the wrong person's sanction to a
client, which is worse than finding nothing. Every DNI/NIE/CIF-shaped token is
checksum-validated before being accepted, and free-floating uppercase runs are
never treated as names unless anchored near an identifier or a legal-form
suffix.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MAX_IDENTIFICADORES = 2_000
MAX_NOMBRES = 1_000
MAX_MATRICULAS = 1_000
MAX_TEXTO_ANALIZADO = 400_000

_DNI_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIJO = {"X": "0", "Y": "1", "Z": "2"}
_CIF_LETRAS_SOLO = set("ABEH")  # digit-only control char
_CIF_LETRAS_LETRA = set("PQRSNW")  # letter-only control char
_CIF_CONTROL_MAP = "JABCDEFGHI"

# ---------------------------------------------------------------------------
# Candidate patterns. Boundaries use negative look-around, not \b, because \b
# treats '*' and '-' as non-word characters and would still match inside a
# longer alphanumeric token such as an expediente reference.
# ---------------------------------------------------------------------------

DNI_RE = re.compile(r"(?<![A-Z0-9*])(\d{8})[ .\-]?([A-HJ-NP-TV-Z])(?![A-Z0-9])", re.I)
NIE_RE = re.compile(r"(?<![A-Z0-9*])([XYZ])[ .\-]?(\d{7})[ .\-]?([A-HJ-NP-TV-Z])(?![A-Z0-9])", re.I)
CIF_RE = re.compile(r"(?<![A-Z0-9*])([ABCDEFGHJNPQRSUVW])[ .\-]?(\d{7})[ .\-]?([0-9A-J])(?![A-Z0-9])", re.I)

# BOE ordinario masks the DNI (LOPDGDD DA7): a 9-char token of digits/asterisks,
# e.g. "***4567**". Kept verbatim — the asterisk POSITIONS carry information —
# and never "resolved" to a real DNI; matching against a client is positional
# (see dni_encaja_con_mascara).
DNI_MASCARA_RE = re.compile(r"(?<![\w*])([0-9*]{8}[0-9A-Z*])(?![\w*])")

# Post-2000 plate: 4 digits + 3 consonants (no vowels, no Ñ, no Q) — accepted
# without extra context, the trigram shape is already near-unambiguous.
MATRICULA_NUEVA_RE = re.compile(r"(?<![A-Z0-9\-])(\d{4})[ \-]?([BCDFGHJKLMNPRSTVWXYZ]{3})(?![A-Z0-9\-])", re.I)
# Pre-2000 provincial plate: only accepted with a province prefix AND a
# vehicle-context word nearby — otherwise this shape collides constantly with
# BOE references, article numbers and amounts.
MATRICULA_ANTIGUA_RE = re.compile(r"(?<![A-Z0-9\-])([A-Z]{1,2})[ \-]?(\d{4})[ \-]?([A-Z]{1,2})(?![A-Z0-9\-])")
CONTEXTO_VEHICULO_RE = re.compile(r"matr[ií]cula|veh[ií]culo|turismo|remolque|ciclomotor|placa", re.I)

PROVINCIAS_MATRICULA = {
    "A", "AB", "AL", "AV", "B", "BA", "BI", "BU", "C", "CA", "CC", "CE", "CO", "CR", "CS", "CU",
    "GC", "GE", "GI", "GR", "GU", "H", "HU", "IB", "J", "L", "LE", "LO", "LU", "M", "MA", "ML",
    "MU", "NA", "O", "OR", "OU", "P", "PM", "PO", "S", "SA", "SE", "SG", "SO", "SS", "T", "TE",
    "TF", "TO", "V", "VA", "VI", "Z", "ZA",
}

# Rejects a candidate whose immediate left context looks like a reference
# number, article, or account rather than a person's document. Whole-word
# tokens are wrapped in \b so they cannot match inside an unrelated word (e.g.
# "núm" inside "número"); the symbol/punctuation forms (n.º, art., r.d.) carry
# their own natural boundaries and are intentionally NOT \b-wrapped, since a
# trailing literal "." is itself non-word and would make a following \b fail
# to match.
CONTEXTO_PROHIBIDO_RE = re.compile(
    r"\b(expediente|expte|referencia|csv|iban|numero|n[uú]m|factura|cuenta|"
    r"art[ií]culo|disposicion|disposici[oó]n|resolucion|resoluci[oó]n|orden)\b"
    r"|n[º°]|n\.º|art\.|r\.d\.",
    re.I,
)

# Company names: require a legal-form suffix. No suffix => not a company name.
RAZON_SOCIAL_RE = re.compile(
    r"([A-ZÑÁÉÍÓÚÜ0-9][A-ZÑÁÉÍÓÚÜ0-9&.,'’\- ]{2,88}?)[ ,]+"
    r"(S\.?\s?L\.?U?|S\.?\s?A\.?U?|S\.?\s?COOP|S\.?\s?L\.?\s?L|C\.?\s?B|S\.?\s?C|A\.?I\.?E|U\.?T\.?E)\b\.?"
)

# Natural persons: only harvested from a window immediately preceding a
# (masked or full) identifier — free-floating uppercase runs elsewhere in the
# document are never treated as a person's name.
NOMBRE_ANTES_ID_RE = re.compile(
    r"([A-ZÑÁÉÍÓÚÜ][A-ZÑÁÉÍÓÚÜ'’\- ]{5,70})[ ,;:]*(?:con\s+)?"
    r"(?:D\.?N\.?I\.?|N\.?I\.?F\.?|N\.?I\.?E\.?|C\.?I\.?F\.?|documento)?[ .:nºNº\-]*"
    r"(?=[0-9*XYZ])"
)

_ORGANISMOS_STOPWORDS = (
    "BOLETIN OFICIAL", "MINISTERIO", "DIRECCION GENERAL", "SUBDELEGACION", "DELEGACION",
    "AYUNTAMIENTO", "JEFATURA", "CONSEJERIA", "TESORERIA", "AGENCIA ESTATAL",
    "SEGURIDAD SOCIAL", "JUZGADO", "TRIBUNAL", "RESOLUCION", "EXPEDIENTE", "ANEXO",
    "ARTICULO", "DISPOSICION", "REAL DECRETO", "ANUNCIO", "EDICTO", "NOTIFICACION",
)

_SEPARADOR_NOMBRES = " zzsep "


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_identificador(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[\s.\-]", "", value).upper()


def normalizar_matricula(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[\s.\-]", "", value).upper()


def normalizar_nombre(value: str | None) -> str:
    """Accent-free, uppercased, whitespace-collapsed — the exact shape stored
    in ``nombres_norm`` and searched by the generated ``tsv`` column."""
    if not value:
        return ""
    text = _strip_accents(value).upper()
    text = re.sub(r"[.,]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _validar_dni_nie(numero: str, letra: str) -> bool:
    try:
        n = int(numero)
    except ValueError:
        return False
    return _DNI_LETRAS[n % 23] == letra.upper()


def validar_dni(numero: str, letra: str) -> bool:
    return _validar_dni_nie(numero, letra)


def validar_nie(prefijo: str, numero: str, letra: str) -> bool:
    prefijo_num = _NIE_PREFIJO.get(prefijo.upper())
    if prefijo_num is None:
        return False
    return _validar_dni_nie(prefijo_num + numero, letra)


def validar_cif(letra_org: str, numero: str, control: str) -> bool:
    if len(numero) != 7 or not numero.isdigit():
        return False
    total = 0
    for i, digit in enumerate(numero):
        d = int(digit)
        if i % 2 == 0:  # positions 1,3,5,7 (0-indexed 0,2,4,6): double + digit-sum
            doubled = d * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += d
    digito_control = (10 - total % 10) % 10
    letra_org = letra_org.upper()
    control = control.upper()
    if letra_org in _CIF_LETRAS_SOLO:
        return control == str(digito_control)
    if letra_org in _CIF_LETRAS_LETRA:
        return control == _CIF_CONTROL_MAP[digito_control]
    return control == str(digito_control) or control == _CIF_CONTROL_MAP[digito_control]


def _contexto_prohibido(texto: str, start: int) -> bool:
    ventana = texto[max(0, start - 24):start]
    return bool(CONTEXTO_PROHIBIDO_RE.search(ventana))


def _es_organismo(nombre: str) -> bool:
    upper = _strip_accents(nombre).upper()
    return any(stop in upper for stop in _ORGANISMOS_STOPWORDS)


def _extraer_identificadores(texto: str) -> tuple[list[str], list[str]]:
    """Return (identificadores válidos normalizados, máscaras de DNI)."""
    identificadores: list[str] = []
    vistos: set[str] = set()

    for match in DNI_RE.finditer(texto):
        if _contexto_prohibido(texto, match.start()):
            continue
        numero, letra = match.group(1), match.group(2)
        if not validar_dni(numero, letra):
            continue
        valor = f"{numero}{letra.upper()}"
        if valor not in vistos:
            vistos.add(valor)
            identificadores.append(valor)

    for match in NIE_RE.finditer(texto):
        if _contexto_prohibido(texto, match.start()):
            continue
        prefijo, numero, letra = match.group(1), match.group(2), match.group(3)
        if not validar_nie(prefijo, numero, letra):
            continue
        valor = f"{prefijo.upper()}{numero}{letra.upper()}"
        if valor not in vistos:
            vistos.add(valor)
            identificadores.append(valor)

    for match in CIF_RE.finditer(texto):
        if _contexto_prohibido(texto, match.start()):
            continue
        letra_org, numero, control = match.group(1), match.group(2), match.group(3)
        if not validar_cif(letra_org, numero, control):
            continue
        valor = f"{letra_org.upper()}{numero}{control.upper()}"
        if valor not in vistos:
            vistos.add(valor)
            identificadores.append(valor)

    mascaras: list[str] = []
    vistos_mascara: set[str] = set()
    for match in DNI_MASCARA_RE.finditer(texto):
        token = match.group(1).upper()
        if "*" not in token:
            continue  # a fully-visible run here is just an unrelated 9-char code
        if token in vistos:
            continue  # already captured (and validated) as a full identifier
        if token not in vistos_mascara:
            vistos_mascara.add(token)
            mascaras.append(token)

    return identificadores[:MAX_IDENTIFICADORES], mascaras[:MAX_IDENTIFICADORES]


def _extraer_matriculas(texto: str) -> list[str]:
    matriculas: list[str] = []
    vistas: set[str] = set()

    for match in MATRICULA_NUEVA_RE.finditer(texto):
        if _contexto_prohibido(texto, match.start()):
            continue
        valor = f"{match.group(1)}{match.group(2).upper()}"
        if valor not in vistas:
            vistas.add(valor)
            matriculas.append(valor)

    for match in MATRICULA_ANTIGUA_RE.finditer(texto):
        prefijo = match.group(1).upper()
        if prefijo not in PROVINCIAS_MATRICULA:
            continue
        ventana = texto[max(0, match.start() - 80):match.end() + 80]
        if not CONTEXTO_VEHICULO_RE.search(ventana):
            continue
        if _contexto_prohibido(texto, match.start()):
            continue
        valor = f"{prefijo}{match.group(2)}{match.group(3).upper()}"
        if valor not in vistas:
            vistas.add(valor)
            matriculas.append(valor)

    return matriculas[:MAX_MATRICULAS]


def _extraer_nombres(texto: str) -> list[str]:
    nombres: list[str] = []
    vistos: set[str] = set()

    for match in RAZON_SOCIAL_RE.finditer(texto):
        nombre = f"{match.group(1).strip()} {match.group(2).strip()}"
        if _es_organismo(nombre):
            continue
        if nombre not in vistos:
            vistos.add(nombre)
            nombres.append(nombre)

    for match in NOMBRE_ANTES_ID_RE.finditer(texto):
        candidato = match.group(1).strip(" ,;:-'’")
        if len(candidato) < 6 or _es_organismo(candidato):
            continue
        if candidato not in vistos:
            vistos.add(candidato)
            nombres.append(candidato)

    return nombres[:MAX_NOMBRES]


@dataclass(frozen=True)
class ClavesExtraidas:
    identificadores: list[str] = field(default_factory=list)
    matriculas: list[str] = field(default_factory=list)
    nombres: list[str] = field(default_factory=list)
    digitos_parciales: list[str] = field(default_factory=list)
    nombres_norm: str = ""


def extraer_claves(texto: str, titulo: str = "") -> ClavesExtraidas:
    """Extract identifiers/plates/names from BOE plain text. No LLM, no I/O."""
    cuerpo = f"{titulo}\n{texto or ''}"[:MAX_TEXTO_ANALIZADO]
    identificadores, mascaras = _extraer_identificadores(cuerpo)
    matriculas = _extraer_matriculas(cuerpo)
    nombres = _extraer_nombres(cuerpo)
    nombres_norm = _SEPARADOR_NOMBRES.join(normalizar_nombre(n) for n in nombres if n)
    return ClavesExtraidas(
        identificadores=identificadores,
        matriculas=matriculas,
        nombres=nombres,
        digitos_parciales=mascaras,
        nombres_norm=nombres_norm,
    )


def dni_encaja_con_mascara(dni_completo: str | None, mascara: str | None) -> bool:
    """Positional comparison only — never "resolves" a masked DNI. '*' in the
    mask is a wildcard; every other character must match exactly."""
    if not dni_completo or not mascara:
        return False
    dni = normalizar_identificador(dni_completo)
    mask = mascara.upper()
    if len(dni) != len(mask):
        return False
    return all(m == "*" or m == d for d, m in zip(dni, mask))
