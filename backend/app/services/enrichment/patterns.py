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
# starting with 6/7/8/9 (mobile) or 8/9 (landline). Separators are allowed
# between any digits because real pages group them arbitrarily (3-3-3,
# 3-2-2-2, 2-3-2-2, …). Digit lookarounds reject longer digit runs.
PHONE_RE = re.compile(r"(?<!\d)(?:\+34|0034)?(?:[\s.-]?[6789])(?:[\s.-]?\d){8}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Regex-matched "emails" in raw HTML are often asset filenames (logo@2x.png) or
# documentation placeholders — never real contact addresses.
EMAIL_JUNK_TLDS = frozenset({
    "png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico",
    "woff", "woff2", "ttf", "eot",
})
EMAIL_JUNK_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "domain.com", "email.com",
    "yourdomain.com", "empresa.com", "tudominio.com",
})

# Entity profile URLs. Only profile-shaped paths count: share/intent endpoints
# and platform roots don't identify the entity.
SOCIAL_PATTERNS = {
    "linkedin_url": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|company)/[A-Za-z0-9][A-Za-z0-9\-_%]*"),
    "facebook_url": re.compile(r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9][A-Za-z0-9.\-_]*"),
    "instagram_url": re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9][A-Za-z0-9._]*"),
    "twitter_url": re.compile(r"https?://(?:www\.)?(?:twitter\.com|x\.com)/[A-Za-z0-9][A-Za-z0-9_]*"),
}
SOCIAL_JUNK_SEGMENTS = frozenset({
    "share", "sharer", "sharer.php", "intent", "home", "login", "signup",
    "explore", "p", "stories", "plugins", "dialog", "hashtag", "search",
})

# Aggregators and directories that dominate Spanish company-name searches. Two
# distinct kinds:
# - COMPANY_DATA_DOMAINS publish the entity's own contact data (phone/email) —
#   usable, though never as the entity's website or social profiles.
# - NON_ENTITY_DOMAINS publish their OWN contact data on pages merely about the
#   entity (consumer-complaint sites, social platforms, content farms): nothing
#   may be extracted from their page text; only the candidate URL itself can
#   still be a verified social profile of the entity.
# boe.es is non-entity because the sanction publication itself contains the
# entity's name + identifier, so it would pass verification and could otherwise
# be misattributed as the entity's own site.
COMPANY_DATA_DOMAINS = frozenset({
    "dnb.com", "verif.com", "infoempresa.com", "eleconomista.es", "einforma.com",
    "axesor.es", "datoscif.es", "paginasamarillas.es", "elpais.com",
    "interempresas.net", "nextdoor.com", "empresia.es", "infocif.es",
    "registro-mercantil.com",
})
NON_ENTITY_DOMAINS = frozenset({
    "ocu.org", "facebook.com", "linkedin.com", "instagram.com", "twitter.com",
    "x.com", "boe.es", "significadode.org", "wordmeaning.org", "abebooks.com",
})
DIRECTORY_DOMAINS = COMPANY_DATA_DOMAINS | NON_ENTITY_DOMAINS

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


def _phone_score(value: str) -> int:
    """Bare 9-digit runs in embedded JSON/JS often match the regex without being
    a phone; numbers written with a country prefix or separators are far more
    likely to be a deliberately published contact number."""
    score = 0
    if value.startswith(("+34", "0034")):
        score += 2
    if any(sep in value for sep in (" ", ".", "-")):
        score += 1
    return score


def _is_junk_email(value: str) -> bool:
    domain = value.lower().rpartition("@")[2]
    tld = domain.rpartition(".")[2]
    return tld in EMAIL_JUNK_TLDS or domain in EMAIL_JUNK_DOMAINS


def find_phones(text: str) -> list[str]:
    found = _dedupe(match.group(0).strip() for match in PHONE_RE.finditer(text))
    # Stable sort: highest-signal formatting first, original order within ties.
    return sorted(found, key=lambda value: -_phone_score(value))


def find_emails(text: str) -> list[str]:
    found = _dedupe(match.group(0) for match in EMAIL_RE.finditer(text))
    return [value for value in found if not _is_junk_email(value)]


def find_social(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for field, pattern in SOCIAL_PATTERNS.items():
        urls: list[str] = []
        for match in pattern.finditer(text):
            url = match.group(0).rstrip("/")
            segment = url.rpartition("/")[2].lower()
            if segment in SOCIAL_JUNK_SEGMENTS:
                continue
            if url not in urls:
                urls.append(url)
        if urls:
            found[field] = urls
    return found


def is_generic_directory(domain: str) -> bool:
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == item or domain.endswith("." + item) for item in DIRECTORY_DOMAINS)


def is_non_entity_site(domain: str) -> bool:
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == item or domain.endswith("." + item) for item in NON_ENTITY_DOMAINS)
