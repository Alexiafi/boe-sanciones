"""Regex extraction of contact data from a downloaded web page.

Deliberately conservative. A false positive here silently attributes the wrong
entity's phone number to a sanctioned party — worse than finding nothing. These
patterns only produce *candidates*; ``verify.py`` decides whether the page has
enough evidence to actually be about the searched entity before anything is
persisted.
"""

from __future__ import annotations

import re

# Spanish mobile/landline numbers: optional +34/0034 prefix, then 9 digits
# starting with 6/7/8/9 (mobile) or 8/9 (landline), tolerant of common
# separators. Intentionally does not match short codes or generic digit runs.
PHONE_RE = re.compile(r"(?:\+34|0034)?[\s.-]?[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Links whose href or visible text hints they hold LSSI-CE mandated identity
# data (Spanish law requires businesses to publish CIF + contact on their own
# site under "aviso legal"), which makes these the highest-value pages to
# follow from a company's homepage.
LEGAL_LINK_HINTS = (
    "aviso-legal", "aviso_legal", "aviso legal", "legal", "contacto", "contact",
    "quienes-somos", "quienes somos", "sobre-nosotros",
)


def _dedupe(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def find_phones(text: str) -> list[str]:
    return _dedupe(match.group(0).strip() for match in PHONE_RE.finditer(text))


def find_emails(text: str) -> list[str]:
    return _dedupe(match.group(0) for match in EMAIL_RE.finditer(text))
