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
    # Their pages carry the directory's own customer-service line in the header/footer
    # (iberinform: 900 213 215 / atencionclientes@iberinform.es was stored as a company's).
    "iberinform.es", "librebor.me", "universia.es", "cylex.es", "infobel.com", "kompass.com",
    "europages.es", "europages.com", "expansion.com", "11870.com", "qdq.com", "hotfrog.es",
    "opencorporates.com", "dateas.com", "sociedad.info", "infonif.es", "cifempresa.es",
    "guiaempresas.es", "empresas.es", "informacion-empresas.es", "boletinempresas.es",
    "infoentidades.es", "monitorempresas.es", "yelp.es", "tripadvisor.es",
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
    # RGPD privacy policies name the data controller with CIF, address and phone.
    "privacidad", "privacy",
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
    chunk = text[max(0, start - 70): start]
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


# ---------------------------------------------------------------------------
# Attribution: which phone/email on a page belongs to THIS party.
#
# A page "about" a company (it carries the CIF or the exact razón social) also
# carries numbers that are not the company's: the directory's own customer line in
# its header/footer (iberinform 900 213 215), "other companies" sidebars with their
# own CIF and phone, or — on an official notice — the issuing office's line. Only
# what sits next to the party's own identifier or name, and before the next
# party's identifier, is attributed to it.
# ---------------------------------------------------------------------------

_TAGS_SIN_TEXTO = ("script", "style", "noscript", "svg", "template", "iframe", "head", "select", "button")
_TAGS_MARCO = ("footer", "nav", "aside")
_CLASE_MARCO_RE = re.compile(r"footer|cookie|navbar|topbar|breadcrumb", re.IGNORECASE)

# CIF (letter + 7 digits + control), DNI (8 digits + letter, dotted or not), NIE.
_ID_EN_TEXTO_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[ABCDEFGHJKLMNPQRSUVW][\s.\-]?\d{7}[\s.\-]?[0-9A-J]"
    r"|\d{2}\.?\d{3}\.?\d{3}[\s\-]?[A-Z]"
    r"|[XYZ][\s.\-]?\d{7}[\s.\-]?[A-Z]"
    r")(?![A-Za-z0-9])"
)

# Words of an official notice / gazette / tender page: the only contact on it is the office's.
_PALABRAS_OFICIALES = (
    "notificacion", "expediente", "procedimiento sancionador", "boletin oficial", "edicto",
    "resolucion", "ayuntamiento", "jefatura provincial de trafico", "agencia tributaria",
    "diputacion", "tablon", "providencia de apremio", "recaudacion", "licitacion", "adjudicacion",
    "denuncia", "organo de contratacion", "sede electronica", "en virtud de lo dispuesto",
)

# Path shapes of a company-directory record (an unknown directory is still a directory).
_RUTA_DIRECTORIO_RE = re.compile(
    r"(?:^|/)(?:empresas|informacion-empresa|ficha-empresa|directorio(?:-empresas)?|"
    r"companies|company-profile|informes-empresas|telefono-direccion)(?:/|$|[-_])",
    re.IGNORECASE,
)

# Name tokens too common to tell a company's own domain apart.
_PALABRAS_GENERICAS = frozenset({
    "GRUPO", "SOLUCIONES", "SERVICIOS", "SERVICES", "ESPANA", "SPAIN", "SOCIEDAD", "LIMITADA",
    "ANONIMA", "GLOBAL", "GESTION", "INVERSIONES", "CONSTRUCCIONES", "TRANSPORTES", "HERMANOS",
    "INTERNACIONAL", "EMPRESA", "COMERCIAL", "INMOBILIARIA", "PROYECTOS", "DESARROLLO", "OBRAS",
    "LOGISTICA", "CONSULTING", "COMPANY", "GROUP", "TRADING", "IBERICA", "NORTE", "LEVANTE",
})
_FORMAS_LEGALES = frozenset({
    "SA", "SAU", "SL", "SLU", "SLL", "SRL", "SGIIC", "SICAV", "AIE", "UTE", "CB", "SC", "SCP",
    "SOCIEDAD", "LIMITADA", "ANONIMA", "UNIPERSONAL", "COOPERATIVA", "SCOOP",
})
_PLIEGUE = str.maketrans("ÁÉÍÓÚÜÀÈÌÒÙÂÊÎÔÛÄËÏÖÑÇáéíóúüàèìòùâêîôûäëïöñç", "AEIOUUAEIOUAEIOUAEIONCaeiouuaeiouaeiouaeionc")


def _plegar(texto: str) -> str:
    """Upper-case and accent-free with the SAME length, so positions still match."""
    return texto.translate(_PLIEGUE).upper()


def clave_compacta(valor: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", _plegar(valor or ""))


def texto_visible(html: str, *, sin_marco: bool = False) -> str:
    """The text a person sees. ``tel:``/``mailto:`` links become text where they
    stand, so they are judged by their position like any other number. With
    ``sin_marco`` the page frame (footer, nav, sidebars, cookie bars) goes too:
    on a directory that is where its OWN phone and email live."""
    if not html:
        return ""
    if "<" not in html:
        return re.sub(r"\s+", " ", html).strip()
    from bs4 import BeautifulSoup, Comment

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml always present in the image
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_TAGS_SIN_TEXTO):
        tag.decompose()
    for comentario in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comentario.extract()
    if sin_marco:
        for tag in soup(_TAGS_MARCO):
            tag.decompose()
        # The site header (logo, menu, the site's own phone) — not a record's
        # <header> inside <main>/<article>, nor one holding the page title.
        for tag in list(soup("header")):
            if getattr(tag, "decomposed", False) or tag.find("h1") or tag.find_parent(("main", "article")):
                continue
            tag.decompose()
        for tag in list(soup.find_all(True)):
            if getattr(tag, "decomposed", False) or tag.name in ("html", "body", "main", "article"):
                continue
            attrs = tag.attrs or {}
            clases = attrs.get("class") or []
            marcas = " ".join(clases if isinstance(clases, list) else [str(clases)]) + " " + str(attrs.get("id") or "")
            if marcas.strip() and _CLASE_MARCO_RE.search(marcas):
                tag.decompose()
    for enlace in soup.find_all("a", href=True):
        href = enlace["href"].strip()
        if href.lower().startswith("tel:"):
            enlace.replace_with(f" Tel. {href[4:]} ")
        elif href.lower().startswith("mailto:"):
            enlace.replace_with(f" {href[7:].split('?')[0]} ")
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def identificadores_en_texto(texto: str) -> list[tuple[int, int, str]]:
    """(start, end, compact key) of every DNI/NIE/CIF-shaped token."""
    return [
        (m.start(), m.end(), re.sub(r"[\s.\-]", "", m.group(0)).upper())
        for m in _ID_EN_TEXTO_RE.finditer(texto)
    ]


# Legal form at the end of a name, however it is written: "S.L.", "S L", "SL.", "S.A.U.", "Sociedad Limitada".
_FORMA_FINAL_RE = re.compile(
    r"[\s,.]*(?:S[\s.]*A[\s.]*S|S[\s.]*L[\s.]*(?:U|L|N[\s.]*E)?|S[\s.]*A[\s.]*U?|S[\s.]*C(?:[\s.]*P)?|C[\s.]*B|"
    r"SOCIEDAD\s+(?:LIMITADA|ANONIMA)(?:\s+UNIPERSONAL)?|SCOOP|COOP|SGIIC|SICAV|AIE|UTE)[\s.]*$"
)
# Legal form written right after a name in running text ("…SENSATIONS, S. L. trata…").
_FORMA_TRAS_RE = re.compile(
    r"\s*,?\s*(SOCIEDAD\s+LIMITADA|SOCIEDAD\s+ANONIMA|S[\s.]*A[\s.]*S|S[\s.]*L[\s.]*(?:N[\s.]*E|U|L)?|"
    r"S[\s.]*A[\s.]*U?|S[\s.]*C[\s.]*P|C[\s.]*B|S[\s.]*COOP|COOP|SGIIC|SICAV|AIE|UTE)(?![A-Z])"
)


def _forma_normal(texto: str) -> str:
    compacta = re.sub(r"[\s.,]", "", texto)
    if compacta.startswith("SOCIEDADLIMITADA") or compacta in ("SL", "SLU", "SLL", "SLNE"):
        return "SL"
    if compacta.startswith("SOCIEDADANONIMA") or compacta in ("SA", "SAU"):
        return "SA"
    return compacta


def forma_de_nombre(nombre: str | None) -> str | None:
    """Legal form of a razón social, normalised (SL / SA / SAS / SCP…), or None."""
    m = _FORMA_FINAL_RE.search(_plegar(nombre or "").strip())
    return _forma_normal(m.group(0)) if m and m.group(0).strip(" ,.") else None


def tokens_nombre(nombre: str | None) -> list[str]:
    """Significant words of a razón social, without its legal form."""
    plegado = _FORMA_FINAL_RE.sub("", _plegar(nombre or "").strip())
    palabras = [p for p in re.split(r"[^A-Z0-9]+", plegado) if p]
    return [p for p in palabras if p not in _FORMAS_LEGALES]


def coincidencias_nombre(texto: str, nombre: str | None) -> list[tuple[int, int, str | None]]:
    """Where the razón social (its significant words, in order) appears AS A
    WHOLE NAME, with the legal form written right after it (None if none).
    Right after the name comes a legal form, punctuation or the end — never
    another word of a longer name ("KUBIKA" is not "Kubika Grupo Inmobiliario
    SL") — and a different legal form is a different company ("Ágora
    Patrimonial S.A.S." is not "Ágora Patrimonial S.L.")."""
    tokens = tokens_nombre(nombre)
    if not tokens or len("".join(tokens)) < 5:
        return []
    forma_buscada = forma_de_nombre(nombre)
    plegado = _plegar(texto)
    patron = r"(?<![A-Z0-9])" + r"[\W_]{0,3}".join(re.escape(t) for t in tokens) + r"(?![A-Z0-9])"
    encontradas: list[tuple[int, int, str | None]] = []
    for m in re.finditer(patron, plegado):
        resto = plegado[m.end():m.end() + 40]
        forma_m = _FORMA_TRAS_RE.match(resto)
        forma = _forma_normal(forma_m.group(1)) if forma_m else None
        if forma and forma_buscada and forma != forma_buscada:
            continue
        if len(tokens) == 1 and not forma:
            # A one-word name is only that company when its legal form follows.
            continue
        if not forma and not re.match(r"\s*(?:[,.;:|()\-»\"'/]|$)", resto):
            siguiente = re.match(r"\s*([A-Z0-9]+)", resto)
            if siguiente and siguiente.group(1) not in _CONECTORES:
                continue
        encontradas.append((m.start(), m.end(), forma))
    return encontradas


def posiciones_nombre(texto: str, nombre: str | None) -> list[tuple[int, int]]:
    return [(s, e) for s, e, _ in coincidencias_nombre(texto, nombre)]


def menciona_nombre_con_forma(texto: str | None, nombre: str | None) -> bool:
    """The full razón social WITH its legal form: what an aviso legal / privacy
    policy writes, and what a homonymous brand abroad does not."""
    return bool(texto) and any(forma for _, _, forma in coincidencias_nombre(texto, nombre))


# Words that may follow a complete name in running text ("Moldes Diaz es una empresa…").
_CONECTORES = frozenset({
    "ES", "EN", "CON", "SE", "TIENE", "FUE", "ESTA", "SU", "SUS", "NIF", "CIF", "TELEFONO", "TEL",
    "TFNO", "DIRECCION", "DOMICILIO", "INFORME", "DATOS", "EMAIL", "WEB", "UBICADA", "SITUADA",
})


def menciona_nombre(texto: str | None, nombre: str | None) -> bool:
    return bool(texto) and bool(posiciones_nombre(texto, nombre))


def contacto_cercano(
    texto: str, identificador: str | None, nombre: str | None, *, despues: int = 700, antes: int = 250,
) -> tuple[list[str], list[str]]:
    """Phones and emails that sit next to the party's identifier (or, failing
    that, its razón social), closest first, never past another party's
    identifier. Nothing when the page never names the party."""
    clave = clave_compacta(identificador)
    ids = identificadores_en_texto(texto)
    anclas = [(s, e) for s, e, c in ids if len(clave) >= 8 and c == clave]
    if not anclas:
        anclas = posiciones_nombre(texto, nombre)
    if not anclas:
        return [], []
    otros = [(s, e) for s, e, c in ids if c != clave]

    telefonos: dict[str, tuple[int, str]] = {}
    emails: dict[str, int] = {}
    for inicio, fin in anclas:
        lo = max(0, inicio - antes)
        hi = min(len(texto), fin + despues)
        for s, e in otros:
            if e <= inicio:
                lo = max(lo, e)
            elif s >= fin:
                hi = min(hi, s)
        tramo = texto[lo:hi]
        for m in PHONE_RE.finditer(tramo):
            raw = "".join(part for part in m.groups() if part)
            if not _looks_like_published_phone(raw, tramo, m.start()):
                continue
            nacional = national_digits(raw)
            if not nacional:
                continue
            distancia = abs(lo + m.start() - inicio)
            if nacional not in telefonos or distancia < telefonos[nacional][0]:
                telefonos[nacional] = (distancia, raw.strip())
        for m in EMAIL_RE.finditer(tramo):
            valor = m.group(0)
            if _is_junk_email(valor):
                continue
            distancia = abs(lo + m.start() - inicio)
            clave_email = valor.lower()
            if clave_email not in emails or distancia < emails[clave_email]:
                emails[clave_email] = distancia
    return (
        [raw for _, raw in sorted(telefonos.values())],
        [valor for valor, _ in sorted(emails.items(), key=lambda item: item[1])],
    )


def parece_directorio(url: str, identificador: str | None = None) -> bool:
    """Known directory, or a page shaped like a company-directory record."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    if is_generic_directory(parsed.netloc):
        return True
    clave = clave_compacta(identificador)
    if len(clave) >= 8 and clave in clave_compacta(unquote(parsed.path + parsed.query)):
        return True
    return bool(_RUTA_DIRECTORIO_RE.search(parsed.path))


def parece_pagina_oficial(texto: str, identificador: str | None = None) -> bool:
    """An official notice, gazette, tender or any list of several parties: none
    of the contact data on it is the party's."""
    plano = _plegar(texto).lower()
    if sum(1 for palabra in _PALABRAS_OFICIALES if palabra in plano) >= 3:
        return True
    clave = clave_compacta(identificador)
    otros = {c for _, _, c in identificadores_en_texto(texto) if c != clave}
    return len(otros) >= 3


def dominio_parecido(dominio: str, nombre: str | None) -> bool:
    """The domain looks like the company's own (``gestfy.com`` for Gestfy Soluciones)."""
    etiqueta = dominio.lower()
    if etiqueta.startswith("www."):
        etiqueta = etiqueta[4:]
    etiqueta = clave_compacta(etiqueta.rsplit(".", 1)[0])
    utiles = [t for t in tokens_nombre(nombre) if len(t) >= 4 and t not in _PALABRAS_GENERICAS]
    return any(t in etiqueta for t in utiles)


def email_del_sitio(email: str, dominio: str) -> bool:
    """The address belongs to the site that publishes it (or to any known directory)."""
    dominio_email = email.lower().rpartition("@")[2]
    base = dominio.lower()
    if base.startswith("www."):
        base = base[4:]
    raiz = ".".join(base.split(".")[-2:])
    return dominio_email == base or dominio_email.endswith("." + raiz) or dominio_email == raiz or is_generic_directory(dominio_email)


def razon_de_titulo(titulo: str | None) -> str | None:
    """Company name at the start of a directory result title:
    'GRUPO BOHEME SENSATIONS SL - NIF B98854250 - Infonif', 'Moldes Diaz SA: consulte…'."""
    if not titulo:
        return None
    m = _RAZON_SOCIAL_RE.search(titulo.split(" | ")[0])
    if m:
        nombre = re.sub(r"\s+", " ", m.group(1)).strip(" -,|«»\"")
        forma = re.sub(r"[\s.]", "", m.group(2)).upper()
        if len(nombre) >= 3:
            return f"{nombre} {forma}"
    m = re.search(r"^(.+?)\s+(Sociedad Limitada|Sociedad An[oó]nima)\b", titulo, re.IGNORECASE)
    if m:
        return f"{m.group(1).strip()} {'SL' if 'limitada' in m.group(2).lower() else 'SA'}"
    return None


def limpiar_razon(razon: str | None) -> str | None:
    """A discovered name without identifiers glued to it ('B55257109 ACCESORIOS DORADOS SL')."""
    if not razon:
        return None
    limpio = re.sub(r"\s+", " ", _ID_EN_TEXTO_RE.sub(" ", razon)).strip(" -,|:;")
    limpio = re.sub(r"^(?:NIF|CIF|N\.I\.F\.|C\.I\.F\.)\s*:?\s*", "", limpio, flags=re.IGNORECASE)
    return limpio if len(limpio) >= 3 else None


def perfil_parecido(url: str, nombre: str | None, dominio: str | None) -> bool:
    """A social profile whose handle looks like the party (its name or its own domain)."""
    handle = clave_compacta(url.rstrip("/").rsplit("/", 1)[-1])
    if len(handle) < 3:
        return False
    utiles = [t for t in tokens_nombre(nombre) if len(t) >= 4 and t not in _PALABRAS_GENERICAS]
    if any(t in handle for t in utiles):
        return True
    if dominio:
        etiqueta = dominio.lower()
        etiqueta = etiqueta[4:] if etiqueta.startswith("www.") else etiqueta
        etiqueta = clave_compacta(etiqueta.rsplit(".", 1)[0])
        return len(etiqueta) >= 4 and (etiqueta in handle or handle in etiqueta)
    return False
