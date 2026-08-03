"""Evidence-based confidence scoring.

This is the rule that stops the pipeline from guessing: a page is only treated
as "about" the sanctioned party when its own identifier (CIF/NIF) or its exact
name/company name is found in the page text. Search ranking, domain
plausibility, or "looks likely" are never enough on their own — anything below
``settings.enrichment_min_confidence`` is discarded upstream as
``no_encontrado`` before a phone or email is ever written to the database.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def _normalise(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value).strip().upper()


def _strip_separators(value: str) -> str:
    return re.sub(r"[\s.-]", "", value)


@dataclass(frozen=True)
class VerificationOutcome:
    confidence: float
    evidencia: str | None


def verify(*, page_text: str, identificador: str | None, nombre: str | None) -> VerificationOutcome:
    """Score how likely ``page_text`` is to genuinely be about this entity.

    - CIF/NIF match (identifier is Spain's official, near-unique business/person
      key) => high confidence (0.9).
    - Exact name/razón social match, with no identifier confirmation => medium
      confidence (0.6): common names can collide, so this alone should sit
      right at a configurable minimum threshold, not comfortably above it.
    - Neither => 0.0, no evidence at all.
    """
    normalised_page = _strip_separators(_normalise(page_text))

    identifier = _strip_separators(_normalise(identificador))
    if identifier and len(identifier) >= 8 and identifier in normalised_page:
        return VerificationOutcome(confidence=0.9, evidencia=f"Identificador {identificador} encontrado en la página")

    name = _normalise(nombre)
    if name and len(name) > 3 and _strip_separators(name) in normalised_page:
        return VerificationOutcome(confidence=0.6, evidencia=f"Nombre/razón social '{nombre}' encontrado en la página")

    return VerificationOutcome(confidence=0.0, evidencia=None)
