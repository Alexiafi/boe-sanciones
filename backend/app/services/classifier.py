"""Rule-based classifier to detect sanction/embargo/debt-related BOE publications."""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# TITLE-BASED PATTERNS
# ---------------------------------------------------------------------------

STRONG_TITLE_PATTERNS = [
    re.compile(r"\bexpediente(?:s)?\s+sancionador(?:es)?\b", re.I),
    re.compile(r"\bprocedimiento(?:s)?\s+sancionador(?:es)?\b", re.I),
    re.compile(r"\bpropuesta de resolución\b", re.I),
    re.compile(r"\bnotificación de resolución\b", re.I),
    re.compile(r"\bpublican las sanciones\b", re.I),
    re.compile(r"\bsanciones por infracciones\b", re.I),
    re.compile(r"\bsanción por infracción\b", re.I),
    re.compile(r"\bnotifica(?:r|ción)?\b.*\bsancionador\b", re.I),
    re.compile(r"\brevocación de procedimientos sancionadores\b", re.I),
    re.compile(r"\bembargo\b", re.I),
    re.compile(r"\bdiligencia de embargo\b", re.I),
    re.compile(r"\bapremio\b", re.I),
    re.compile(r"\bvía de apremio\b", re.I),
    re.compile(r"\brequerimiento de pago\b", re.I),
    re.compile(r"\bdeuda(?:s)?\b.*\bnotifica\b", re.I),
    re.compile(r"\bliquidaci[oó]n\b.*\bdeuda\b", re.I),
    re.compile(r"\bprovidencia de apremio\b", re.I),
    re.compile(r"\bcobro\s+(?:de\s+)?deudas?\b", re.I),
]

MEDIUM_TITLE_PATTERNS = [
    re.compile(r"\bsanción(?:es)?\b", re.I),
    re.compile(r"\bmulta(?:s)?\b", re.I),
    re.compile(r"\binfracci[oó]n(?:es)?\b", re.I),
    re.compile(r"\bexpediente\b", re.I),
    re.compile(r"\bnotificaci[oó]n\b", re.I),
    re.compile(r"\bresoluci[oó]n\b", re.I),
    re.compile(r"\bincoad[oa]\b", re.I),
    re.compile(r"\bembargo\b", re.I),
    re.compile(r"\bdeuda\b", re.I),
    re.compile(r"\bapremio\b", re.I),
    re.compile(r"\bejecuci[oó]n\b", re.I),
]

NORMATIVE_PREFIXES = (
    "ley ", "real decreto ", "real decreto-ley ", "orden ",
)

# Documents from these sections never contain sanctions/embargos
SKIP_SECTIONS = {"1", "2A", "2B"}

SANCTION_SECTIONS = {"3", "4", "5", "5A", "5B", "5C"}

# ---------------------------------------------------------------------------
# BODY-BASED PATTERNS (scored by weight)
# ---------------------------------------------------------------------------

BODY_STRONG = [
    (r"\bexpediente\s+sancionador\b", "body:expediente_sancionador", 3),
    (r"\bprocedimiento\s+sancionador\b", "body:procedimiento_sancionador", 3),
    (r"\bresoluci[oó]n\s+sancionadora\b", "body:resolucion_sancionadora", 3),
    (r"\bdiligencia\s+de\s+embargo\b", "body:diligencia_embargo", 3),
    (r"\bprovidencia\s+de\s+apremio\b", "body:providencia_apremio", 3),
    (r"\brequerimiento\s+de\s+pago\b", "body:requerimiento_pago", 3),
    (r"\bvía\s+de\s+apremio\b", "body:via_apremio", 3),
    (r"\bpago\s+voluntario\b", "body:pago_voluntario", 2),
    (r"\binfracci[oó]n(?:es)?\s+(?:grave|muy\s+grave|leve)\b", "body:tipo_infraccion", 3),
    (r"\bsanción\s+(?:de|por)\b", "body:sancion_de", 2),
    (r"\bsancionad[oa]\b", "body:sancionado", 3),
    (r"\bembarg[oa](?:do|da|r|mos)?\b", "body:embargo", 2),
    (r"\bdeud(?:a|or|ora)(?:s)?\b", "body:deuda", 1),
    (r"\bmulta\s+de\s+\d", "body:multa_importe", 3),
    (r"\breducci[oó]n\s+de\s+la\s+sanci[oó]n\b", "body:reduccion_sancion", 2),
    (r"\bpotestad\s+sancionadora\b", "body:potestad_sancionadora", 2),
]

BODY_MEDIUM = [
    (r"\bmulta(?:s|do)?\b", "body:multa", 1),
    (r"\binfracci[oó]n(?:es)?\b", "body:infraccion", 1),
    (r"\bsanci[oó]n(?:es)?\b", "body:sancion", 1),
    (r"\bapremio\b", "body:apremio", 1),
    (r"\bresponsable\b", "body:responsable", 1),
    (r"\bimpago\b", "body:impago", 1),
    (r"\bmoroso\b", "body:moroso", 2),
    (r"\bcr[eé]dito\s+incobrable\b", "body:credito_incobrable", 2),
    (r"\bresolvi[oó]\s+(?:declarar|sancionar|imponer)\b", "body:resolvio_sancionar", 3),
]

# Signals that DISQUALIFY a document (convenios, formación, normativa general)
BODY_DISQUALIFIERS = [
    (r"\bestancias?\s+formativas?\b", "disq:estancia_formativa"),
    (r"\bplan\s+de\s+formaci[oó]n\b", "disq:plan_formacion"),
    (r"\btutor(?:a)?\s+dual\b", "disq:tutor_dual"),
    (r"\bconvenio\b.*\bformaci[oó]n\s+profesional\b", "disq:convenio_fp"),
    (r"\bciclos?\s+(?:de\s+)?grado\b", "disq:ciclo_grado"),
    (r"\bcomisi[oó]n\s+de\s+seguimiento\b.*\bempresa\b", "disq:comision_empresa_fp"),
]

MIN_BODY_SCORE = 3


def classify_document(doc: dict[str, Any]) -> tuple[bool, list[str], float, str]:
    """Title-based fast classification. Returns (is_candidate, rules, confidence, familia)."""
    title = (doc.get("titulo") or "").lower()
    section_code = (doc.get("seccion_codigo") or "").upper()
    section_name = (doc.get("seccion_nombre") or "").lower()
    reasons: list[str] = []

    if title.startswith(NORMATIVE_PREFIXES) and "régimen sancionador" in title:
        return False, ["likely_normative_false_positive"], 0.0, ""

    for pat in STRONG_TITLE_PATTERNS:
        if pat.search(title):
            reasons.append(f"strong:{pat.pattern}")

    if reasons:
        familia = _guess_familia(section_code, section_name)
        return True, reasons, 0.95, familia

    medium_hits = [pat.pattern for pat in MEDIUM_TITLE_PATTERNS if pat.search(title)]
    section_match = section_code in SANCTION_SECTIONS or any(
        s in section_name for s in ("iii.", "iv.", "v.")
    )

    if len(medium_hits) >= 2 and section_match:
        reasons = [f"medium:{p}" for p in medium_hits]
        familia = _guess_familia(section_code, section_name)
        return True, reasons, 0.70, familia

    return False, [], 0.0, ""


def should_skip_section(doc: dict[str, Any]) -> bool:
    """Returns True if this document's section never contains actionable sanctions."""
    sec = (doc.get("seccion_codigo") or "").upper()
    return sec in SKIP_SECTIONS


def _guess_familia(section_code: str, section_name: str) -> str:
    sc = section_code.upper()
    if sc.startswith("5") or "v." in section_name:
        return "anuncio_expediente"
    if sc == "3" or "iii." in section_name:
        return "sancion_firme"
    if sc == "4" or "iv." in section_name:
        return "administracion_justicia"
    return "otro"


def verify_with_body(text: str) -> tuple[bool, list[str]]:
    """
    Score the document body for sanction/embargo signals.
    Also checks for disqualifying patterns (convenios de formación, etc).
    Returns (is_confirmed, signal_labels).
    """
    if not text:
        return False, []

    t = text.lower()

    for disq_pat, _label in BODY_DISQUALIFIERS:
        if re.search(disq_pat, t, re.I):
            return False, [_label]

    signals = []
    score = 0

    for pattern, label, weight in BODY_STRONG:
        if re.search(pattern, t, re.I):
            signals.append(label)
            score += weight

    for pattern, label, weight in BODY_MEDIUM:
        if re.search(pattern, t, re.I):
            signals.append(label)
            score += weight

    return score >= MIN_BODY_SCORE, signals
