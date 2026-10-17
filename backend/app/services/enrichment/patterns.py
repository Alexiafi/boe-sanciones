"""Regex extraction of contact data from a downloaded web page.

Deliberately conservative. A false positive here silently attributes the wrong
entity's phone number to a sanctioned party — worse than finding nothing. These
patterns only produce *candidates*; ``verify.py`` decides whether the page has
enough evidence to actually be about the searched entity before anything is
persisted.
"""

from __future__ import annotations

import re

# Optional +34/0034, then 9 national digits starting with 6/7/8/9. Separators
# are allowed between digits because real pages group them arbitrarily.
PHONE_RE = re.compile(
    r"(?<!\d)((?:\+34|0034)[\s.\-()]*)?([6-9](?:[\s.\-()]*\d){8})(?!\d)"
)
TEL_HREF_RE = re.compile(r"tel:([+\d][\d\s.\-()]{7,24})", re.IGNORECASE)
PHONE_CONTEXT_RE = re.compile(
    r"(?:tel(?:[eé]fono)?s?|tfno|tlfno|tlf|m[oó]vil(?:es)?|fax|"
    r"whats?app|ll[aá]m[aeo]n?o?s?|contact(?:o|ar)?)",
    re.IGNORECASE,
)
# 800/900-range numbers that a company actually publishes as a contact line.
# 803/806/807 (premium/adult) and 908/909 (internet access) are not.
_SPECIAL_PREFIXES = frozenset({"800", "900", "901", "902"})

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
    "finect.com", "investing.com", "cnmv.es",
})
DIRECTORY_DOMAINS = COMPANY_DATA_DOMAINS | NON_ENTITY_DOMAINS

# Links whose href or visible text hints they hold LSSI-CE mandated identity
# data (Spanish law requires businesses to publish CIF + contact on their own
# site under "aviso legal"), which makes these the highest-value pages to
# follow from a company's homepage — and from those pages, one more hop.
LEGAL_LINK_HINTS = (
    "aviso-legal", "aviso_legal", "aviso legal", "legal-notice", "legalnotice",
    "legal", "contacto", "contact", "contactanos", "contáctanos",
    "quienes-somos", "quienes_somos", "quienes somos", "quienessomos",
    "sobre-nosotros", "about-us", "about",
    "sede-social", "sede social", "datos-identificativos",
)


def _dedupe(values) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def is_valid_spanish_national(digits: str) -> bool:
    """True for a 9-digit Spanish national number (mobile, geographic, or a
    published freephone/shared-cost line). Rejects random 9-digit runs that
    merely happen to start with 6-9."""
    if len(digits) != 9 or not digits.isdigit():
        return False
    if digits[0] in "67":
        return True
    if digits[0] in "89":
        if digits[1] == "0":
            return digits[:3] in _SPECIAL_PREFIXES
        return True
    return False


def national_digits(raw: str) -> str | None:
    """Strip +34/0034 and separators; return the 9 national digits or None."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0034"):
        digits = digits[4:]
    elif digits.startswith("34") and len(digits) >= 11:
        digits = digits[2:]
    if is_valid_spanish_national(digits):
        return digits
    return None


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


def _looks_like_published_phone(raw: str, text: str, start: int) -> bool:
    """Accept a candidate only when it is formatted as a phone, sits in a tel:
    URI, or is next to a phone/contact word. A bare 9-digit run in a data-id,
    SKU or script is not a telephone number."""
    compact = re.sub(r"[\s.\-()]", "", raw)
    if compact.startswith(("+34", "0034")):
        return True
    if "-" in raw and "." in raw:
        return False
    if re.search(r"\d{4}", raw) and re.search(r"[\s.\-]", raw):
        # Formatted Spanish numbers group in 2–3 digits. A 4-digit clump with
        # separators is a CSS value or chart point, not a telephone.
        return False
    if any(sep in raw for sep in (" ", ".", "-")):
        return True
    # Stay inside the current HTML text node so a nearby "Tel:" in the previous
    # paragraph cannot legitimize a SKU or order number.
    chunk = text[max(0, start - 40): start]
    chunk = chunk.rsplit(">", 1)[-1]
    return bool(PHONE_CONTEXT_RE.search(chunk))


def _is_junk_email(value: str) -> bool:
    domain = value.lower().rpartition("@")[2]
    tld = domain.rpartition(".")[2]
    return tld in EMAIL_JUNK_TLDS or domain in EMAIL_JUNK_DOMAINS


def find_phones(text: str) -> list[str]:
    """Return distinct Spanish phone numbers, highest-signal form first.

    Dedupes by national digits so ``+34 611 222 333`` and ``611222333`` collapse
    to the better-formatted variant instead of being stored as two contacts.
    """
    best: dict[str, tuple[int, str]] = {}

    def consider(raw: str, extra_score: int = 0) -> None:
        raw = raw.strip()
        national = national_digits(raw)
        if not national:
            return
        score = _phone_score(raw) + extra_score
        current = best.get(national)
        if current is None or score > current[0]:
            best[national] = (score, raw)

    for match in TEL_HREF_RE.finditer(text):
        consider(match.group(1), extra_score=3)
    for match in PHONE_RE.finditer(text):
        raw = "".join(part for part in match.groups() if part)
        if _looks_like_published_phone(raw, text, match.start()):
            consider(raw)
    return [raw for _, raw in sorted(best.values(), key=lambda item: -item[0])]


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
    if any(domain == item or domain.endswith("." + item) for item in NON_ENTITY_DOMAINS):
        return True
    # Public bodies and official gazettes publish the NOTICE (which carries the
    # DNI, so it passes verification) next to their own phone and email.
    from app.services.contacto import es_dominio_institucional

    return es_dominio_institucional(domain, pagina=True)


# Razón social as it appears in eInforma/InfoCIF titles: "FOO BAR SL - Informe".
_RAZON_SOCIAL_RE = re.compile(
    r"([A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9&.,'’\- ]{2,80}?)\s+"
    r"(S\.?\s?L\.?\s?L?\.?\s?U?\.?|S\.?\s?A\.?\s?U?\.?|SLU|SAU|SLL|SL|SA)\b",
    re.IGNORECASE,
)


def extract_razon_social(*texts: str | None) -> str | None:
    """Pull a Spanish company name + legal form out of a directory title/snippet."""
    for text in texts:
        if not text:
            continue
        match = _RAZON_SOCIAL_RE.search(text)
        if not match:
            continue
        nombre = re.sub(r"\s+", " ", match.group(1)).strip(" -,|")
        forma = re.sub(r"[\s.]", "", match.group(2)).upper()
        if len(nombre) < 3:
            continue
        return f"{nombre} {forma}"
    return None


def razon_from_directory_slug(url: str) -> str | None:
    """eInforma-style path `/informacion-empresa/construhogar-gracida-siglo-xxi`."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not is_generic_directory(parsed.netloc):
        return None
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|php)$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    if len(slug) < 10:
        return None
    return slug.upper()
