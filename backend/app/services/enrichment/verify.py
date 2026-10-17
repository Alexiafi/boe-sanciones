"""Evidence-based confidence scoring.

This is the rule that stops the pipeline from guessing: a page is only treated
as "about" the sanctioned party when its own identifier (CIF/NIF) or its
razón social is found in the page text. Search ranking, domain plausibility,
or "looks likely" are never enough on their own — anything below
``settings.enrichment_min_confidence`` is discarded upstream as
``no_encontrado`` before a phone or email is ever written to the database.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Spanish company-form tokens. Stripped from the searched name so
# "Gesconsult, SA, SGIIC" still matches a page that only says "Gesconsult SGIIC".
_LEGAL_FORMS = frozenset({
    "SA", "SAU", "SL", "SLU", "SLL", "SRL", "SGIIC", "SICAV",
    "AIE", "UTE", "CB", "SC", "SCP",
})


def _normalise(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value).strip().upper()


def _compact(value: str) -> str:
    """Alphanumeric-only form so commas, dots and 'S.A.' vs 'SA' collapse."""
    return re.sub(r"[^A-Z0-9]", "", value)


def _name_needles(nombre: str | None) -> list[str]:
    tokens = [token for token in re.split(r"[^A-Z0-9]+", _normalise(nombre)) if token]
    if not tokens:
        return []
    full = "".join(tokens)
    core = "".join(token for token in tokens if token not in _LEGAL_FORMS)
    needles: list[str] = []
    if len(full) > 3:
        needles.append(full)
    # Core without SA/SL/SGIIC: only if long enough to stay distinctive.
    if core and core != full and len(core) >= 6:
        needles.append(core)
    return needles


@dataclass(frozen=True)
class VerificationOutcome:
    confidence: float
    evidencia: str | None


def verify(*, page_text: str, identificador: str | None, nombre: str | None) -> VerificationOutcome:
    """Score how likely ``page_text`` is to genuinely be about this entity.

    - CIF/NIF match (identifier is Spain's official, near-unique business/person
      key) => high confidence (0.9).
    - Razón social match, with no identifier confirmation => medium confidence
      (0.6): common names can collide, so this alone should sit right at a
      configurable minimum threshold, not comfortably above it.
    - Neither => 0.0, no evidence at all.
    """
    page = _compact(_normalise(page_text))

    identifier = _compact(_normalise(identificador))
    if identifier and len(identifier) >= 8 and identifier in page:
        return VerificationOutcome(confidence=0.9, evidencia=f"Identificador {identificador} encontrado en la página")

    for needle in _name_needles(nombre):
        if needle in page:
            return VerificationOutcome(
                confidence=0.6,
                evidencia=f"Nombre/razón social '{nombre}' encontrado en la página",
            )

    return VerificationOutcome(confidence=0.0, evidencia=None)
