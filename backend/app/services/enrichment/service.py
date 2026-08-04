"""Contact-enrichment orchestration: discover -> fetch -> verify -> persist.

This module is where the product's actual value lives: not a URL-to-contact
extractor, but a bounded, auditable search for *where* a sanctioned party's
public contact information lives. Discovery is provider-agnostic (whichever
``SearchProvider`` is configured only supplies candidate URLs); fetching,
following "aviso legal"/"contacto" links, regex extraction, evidence
verification, caching and the audit trail are identical regardless of
provider, so no provider can skip the verification step.

Cost control: every attempt is recorded (found or not), a per-domain rate limit
and page cap bound each attempt, and results are cached by query to avoid
paying for the same lookup twice.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import urllib.robotparser
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.models.enriquecimiento import EnriquecimientoCache, EnriquecimientoIntento
from app.models.sancionado import Sancionado
from app.services.enrichment import patterns
from app.services.enrichment.base import EnrichmentResult, SearchCandidate
from app.services.enrichment.providers import get_provider
from app.services.enrichment.verify import verify as verify_evidence

logger = logging.getLogger(__name__)

# Per-attempt cap on follow-up "aviso legal"/"contacto" pages fetched per
# candidate homepage. Keeps a single attempt bounded even on link-heavy sites.
MAX_LEGAL_LINKS_PER_CANDIDATE = 3
MAX_PAGE_BYTES = 300_000

# Fields transported in EnrichmentResult.detalle and mirrored on Sancionado.
CONTACTO_DETALLE_FIELDS = (
    "telefono", "telefono_secundario", "email", "web",
    "linkedin_url", "facebook_url", "instagram_url", "twitter_url",
)

# A "name" that is really just a fiscal ID (NIF/NIE/CIF: 8-9 alphanumeric chars,
# no spaces). Searching it as a name only returns noise (car parts, ASM code…).
_ID_LIKE_RE = re.compile(r"^[0-9A-Z]{8,9}$")

_TRACKING_KEYS = frozenset({"srsltid", "gclid", "fbclid", "mc_cid", "mc_eid"})
_LOCALE_PREFIX_RE = re.compile(r"^/en(?:-[a-z]{2})?/", re.IGNORECASE)

_last_request_at: dict[str, float] = {}


def _nombre_es_identificador(nombre: str | None) -> bool:
    return bool(nombre) and bool(_ID_LIKE_RE.fullmatch(nombre.strip().upper()))


def _normalise_candidate_url(url: str) -> str:
    """Strip tracking params (srsltid, utm_*, …) and English-locale path
    prefixes so the fetch hits the site's default (Spanish) version — e.g.
    ``northdeco.com/en-dk/pages/aviso-legal?srsltid=…`` rate-limits (429) while
    ``northdeco.com/pages/aviso-legal`` answers 200 with the CIF and contact."""
    parsed = urlparse(url)
    query = "&".join(
        part for part in parsed.query.split("&")
        if part and not (part.split("=", 1)[0].lower() in _TRACKING_KEYS or part.lower().startswith("utm_"))
    )
    path = parsed.path
    for _ in range(2):  # some sites stack locales: /en-in/en/…
        path = _LOCALE_PREFIX_RE.sub("/", path)
    return urlunparse(parsed._replace(path=path, query=query, fragment=""))


class EnrichmentDisabled(ValueError):
    """Raised when enrichment is attempted while disabled or unconfigured."""


def enrichment_available(provider_name: str | None = None) -> tuple[bool, str | None]:
    """Check the cost gates without making any network call.

    Mirrors the double-gate pattern from session 1's OpenAI extraction guard
    (``app.tasks.scraping.run_scraping``): both a global enable flag and a
    concrete, configured provider are required. Used both by API endpoints
    (to return a clear 409) and by the orchestration function itself.
    """
    if not settings.enrichment_enabled:
        return False, "El enriquecimiento de contacto está desactivado (ENRICHMENT_ENABLED=false)."
    name = provider_name or settings.enrichment_search_provider
    if name == "none":
        return False, "No hay proveedor de búsqueda configurado (ENRICHMENT_SEARCH_PROVIDER=none)."
    provider = get_provider(name)
    if provider is None:
        return False, f"Proveedor de búsqueda desconocido: '{name}'."
    if name == "searxng" and not settings.searxng_url:
        return False, "SEARXNG_URL no está configurado."
    if name == "tavily" and not settings.tavily_api_key:
        return False, "TAVILY_API_KEY no está configurado."
    if name == "serper" and not settings.serper_api_key:
        return False, "SERPER_API_KEY no está configurado."
    if name == "dataforseo" and not (settings.dataforseo_login and settings.dataforseo_password):
        return False, "DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD no están configurados."
    return True, None


def _build_query(sancionado: Sancionado) -> str:
    location = sancionado.localidad or sancionado.provincia
    nombre = sancionado.nombre
    if _nombre_es_identificador(nombre):
        # The name field carries no signal beyond the fiscal identifier itself.
        nombre = sancionado.identificador or nombre
    return " ".join(part for part in (nombre, location) if part).strip()


def _cache_key(provider_name: str, query: str) -> str:
    return hashlib.sha256(f"{provider_name}:{query.strip().upper()}".encode("utf-8")).hexdigest()


def _get_cached(db, key: str) -> list[SearchCandidate] | None:
    row = db.get(EnriquecimientoCache, key)
    if row is None:
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return [SearchCandidate(**item) for item in row.payload.get("candidates", [])]


def _set_cache(db, key: str, candidates: list[SearchCandidate]) -> None:
    payload = {"candidates": [asdict(candidate) for candidate in candidates]}
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.enrichment_cache_ttl_days)
    existing = db.get(EnriquecimientoCache, key)
    if existing:
        existing.payload = payload
        existing.expires_at = expires_at
    else:
        db.add(EnriquecimientoCache(clave=key, payload=payload, expires_at=expires_at))


def _respect_rate_limit(domain: str) -> None:
    limit = settings.enrichment_rate_limit_per_domain_s
    if limit <= 0:
        return
    last = _last_request_at.get(domain)
    now = time.monotonic()
    if last is not None:
        wait = limit - (now - last)
        if wait > 0:
            time.sleep(wait)
    _last_request_at[domain] = time.monotonic()


def _robots_allows(url: str, client: httpx.Client) -> bool:
    if not settings.enrichment_respect_robots:
        return True
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        response = client.get(robots_url, timeout=settings.enrichment_http_timeout)
        if response.status_code >= 400:
            return True  # no robots.txt published => allowed
        parser.parse(response.text.splitlines())
    except Exception:
        # Fail-open: an unreachable robots.txt must not silently block every
        # attempt. The rate limit and page cap remain regardless.
        return True
    return parser.can_fetch("boe-sanciones-enrichment", url)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
def _fetch(client: httpx.Client, url: str) -> str:
    response = client.get(url, timeout=settings.enrichment_http_timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text[:MAX_PAGE_BYTES]


def _find_legal_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href, label = match.group(1), re.sub(r"<[^>]+>", " ", match.group(2)).strip().lower()
        haystack = f"{href.lower()} {label}"
        if any(hint in haystack for hint in patterns.LEGAL_LINK_HINTS):
            links.append(urljoin(base_url, href))
    return links[:MAX_LEGAL_LINKS_PER_CANDIDATE]


def _record_attempt(db, sancionado_id: int, result: EnrichmentResult) -> None:
    db.add(EnriquecimientoIntento(
        sancionado_id=sancionado_id,
        proveedor=result.proveedor,
        consulta=result.consulta,
        resultado=result.estado,
        url_origen=result.url_origen,
        confidence=result.confidence or None,
        evidencia=result.evidencia,
        coste_estimado_eur=result.coste_estimado_eur,
        duracion_ms=result.duracion_ms,
        error=result.error,
    ))


def _apply_result(sancionado: Sancionado, result: EnrichmentResult) -> None:
    """Update contact fields. Never called when contacto_estado is "manual" —
    the caller filters that out before reaching this point.

    Enrichment only writes fields it owns: a field previously filled by
    enrichment (its detalle entry matches the current column value) may be
    corrected or cleared by a newer run; a value coming from the BOE extraction
    or a manual edit is never touched. ``contacto_detalle`` is replaced (not
    merged) so provenance always reflects the latest run, never stale data.
    """
    if result.estado == "encontrado":
        detalle = result.detalle or {}
        previous = sancionado.contacto_detalle or {}
        applied: dict[str, dict] = {}
        for field in CONTACTO_DETALLE_FIELDS:
            current = getattr(sancionado, field)
            old = previous.get(field)
            auto_filled = old is not None and old.get("valor") == current
            new = detalle.get(field)
            if new and new.get("valor") and (not current or auto_filled):
                setattr(sancionado, field, new["valor"])
                applied[field] = new
            elif auto_filled:
                # Set by an earlier run, not found by this one: stale, clear it.
                setattr(sancionado, field, None)
        sancionado.contacto_detalle = applied or None
        sancionado.contacto_estado = "encontrado"
        sancionado.contacto_fuente = result.fuente
        sancionado.contacto_url = result.url_origen
        sancionado.contacto_confidence = result.confidence
    else:
        sancionado.contacto_estado = "sin_datos" if result.estado == "sin_datos" else "no_encontrado"
        sancionado.contacto_fuente = None
        sancionado.contacto_url = None
        sancionado.contacto_confidence = None
    sancionado.contacto_actualizado_at = datetime.now(timezone.utc)


def enrich_sancionado(db, sancionado: Sancionado, *, provider_name: str | None = None) -> EnrichmentResult:
    """Run the discovery -> verification cascade for one Sancionado.

    Always records an ``EnriquecimientoIntento`` before returning, including
    "no_encontrado", "omitido" and "error" outcomes, so cost and effectiveness
    can be audited without re-running anything. Raises ``EnrichmentDisabled``
    if the cost gates aren't both open; callers (API/tasks) turn that into a
    409 rather than a crash.
    """
    available, reason = enrichment_available(provider_name)
    if not available:
        raise EnrichmentDisabled(reason)
    name = provider_name or settings.enrichment_search_provider
    provider = get_provider(name)
    assert provider is not None  # enrichment_available() already checked this

    if sancionado.contacto_estado == "manual":
        # A human already resolved this one; automatic enrichment must never
        # overwrite it. Still logged so "why didn't this run" is answerable.
        result = EnrichmentResult(
            estado="omitido", proveedor=provider.name,
            evidencia="Contacto ya fijado manualmente; enriquecimiento automático omitido",
        )
        _record_attempt(db, sancionado.id, result)
        return result

    started = time.monotonic()
    if _nombre_es_identificador(sancionado.nombre) and not (sancionado.localidad or sancionado.provincia):
        # Only a fiscal ID and no location: a web search cannot return anything
        # useful, so don't spend a provider call on it. Marked "sin_datos" (not
        # "no_encontrado") because nothing was actually searched.
        result = EnrichmentResult(
            estado="sin_datos", proveedor=provider.name,
            evidencia="El nombre es solo un identificador fiscal y no hay localidad/provincia; búsqueda web no viable",
            duracion_ms=int((time.monotonic() - started) * 1000),
        )
        _record_attempt(db, sancionado.id, result)
        _apply_result(sancionado, result)
        return result

    query = _build_query(sancionado)
    if not query:
        result = EnrichmentResult(
            estado="no_encontrado", proveedor=provider.name, consulta=query,
            evidencia="Sin nombre ni localidad suficientes para construir una búsqueda",
            duracion_ms=int((time.monotonic() - started) * 1000),
        )
        _record_attempt(db, sancionado.id, result)
        _apply_result(sancionado, result)
        return result

    try:
        result = _run_cascade(db, sancionado, provider, query, started)
    except Exception as exc:
        logger.exception("Enrichment attempt failed for sancionado %s", sancionado.id)
        result = EnrichmentResult(
            estado="error", proveedor=provider.name, consulta=query, error=str(exc)[:2_000],
            duracion_ms=int((time.monotonic() - started) * 1000),
        )
        _record_attempt(db, sancionado.id, result)
        return result

    _record_attempt(db, sancionado.id, result)
    if result.estado in ("encontrado", "no_encontrado"):
        _apply_result(sancionado, result)
    return result


def _merge_fields(campos: dict, text: str, url: str, confidence: float) -> None:
    """Merge contact fields found in one evidence-verified text into ``campos``.

    Per-field, highest evidence confidence wins; on ties, the company's own
    site beats directories/aggregators, and earlier (higher-ranked) candidates
    keep the field otherwise.
    """
    def keep(field: str, valor: str | None) -> None:
        if not valor:
            return
        current = campos.get(field)
        if current is None or confidence > current["confidence"]:
            campos[field] = {"valor": valor, "fuente_url": url, "confidence": confidence}
        elif confidence == current["confidence"]:
            current_domain = urlparse(current["fuente_url"]).netloc
            if patterns.is_generic_directory(current_domain) and not patterns.is_generic_directory(urlparse(url).netloc):
                campos[field] = {"valor": valor, "fuente_url": url, "confidence": confidence}

    phones = patterns.find_phones(text)
    emails = patterns.find_emails(text)
    domain = urlparse(url).netloc
    # The candidate URL itself may be the entity's verified social profile
    # (e.g. a Facebook profile whose snippet carries the full name).
    for field, urls in patterns.find_social(url).items():
        keep(field, urls[0])
    if patterns.is_non_entity_site(domain):
        # Pages about the entity but publishing the platform's own contact
        # data (OCU, social networks, content farms): nothing here is theirs.
        return
    keep("telefono", phones[0] if phones else None)
    keep("telefono_secundario", phones[1] if len(phones) > 1 else None)
    keep("email", emails[0] if emails else None)
    if not patterns.is_generic_directory(domain):
        # Social links on the entity's own site point to the entity; on a
        # directory's page they point to the directory's own accounts.
        for field, urls in patterns.find_social(text).items():
            keep(field, urls[0])
        keep("web", f"{urlparse(url).scheme}://{domain}")


def _run_cascade(db, sancionado: Sancionado, provider, query: str, started: float) -> EnrichmentResult:
    cache_key = _cache_key(provider.name, query)
    candidates = _get_cached(db, cache_key)
    if candidates is None:
        candidates = provider.buscar(query, settings.enrichment_max_pages_per_attempt)
        _set_cache(db, cache_key, candidates)

    if not candidates:
        return EnrichmentResult(
            estado="no_encontrado", proveedor=provider.name, consulta=query,
            duracion_ms=int((time.monotonic() - started) * 1000),
            coste_estimado_eur=provider.coste_estimado_por_consulta,
        )

    campos: dict[str, dict] = {}
    best_confidence = 0.0
    best_url: str | None = None
    best_domain: str | None = None
    best_evidencia: str | None = None
    blocked_by_robots = 0
    fetch_errors = 0
    fetched_any = False

    def absorb(text: str, url: str) -> None:
        nonlocal best_confidence, best_url, best_domain, best_evidencia
        outcome = verify_evidence(
            page_text=text, identificador=sancionado.identificador, nombre=sancionado.nombre,
        )
        if outcome.confidence < settings.enrichment_min_confidence:
            return
        if outcome.confidence > best_confidence:
            best_confidence = outcome.confidence
            best_url = url
            best_domain = urlparse(url).netloc
            best_evidencia = outcome.evidencia
        _merge_fields(campos, text, url, outcome.confidence)

    with httpx.Client(headers={"User-Agent": "boe-sanciones-enrichment/1.0"}) as client:
        for candidate in candidates:
            url = _normalise_candidate_url(candidate.url)
            domain = urlparse(url).netloc
            # The provider's own snippet often already carries CIF + phone/email;
            # mining it costs nothing and survives the target page 403ing.
            snippet = " ".join(part for part in (candidate.title, candidate.snippet) if part)
            if snippet:
                absorb(snippet, url)
            if not _robots_allows(url, client):
                blocked_by_robots += 1
                continue
            try:
                _respect_rate_limit(domain)
                html = _fetch(client, url)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", url, exc)
                fetch_errors += 1
                continue
            fetched_any = True

            pages = [(url, html)]
            for legal_url in _find_legal_links(html, url):
                try:
                    _respect_rate_limit(urlparse(legal_url).netloc)
                    pages.append((legal_url, _fetch(client, legal_url)))
                except Exception:
                    continue

            for page_url, page_html in pages:
                absorb(page_html, page_url)

    duracion_ms = int((time.monotonic() - started) * 1000)
    if campos:
        def valor(field: str) -> str | None:
            dato = campos.get(field)
            return dato["valor"] if dato else None

        return EnrichmentResult(
            estado="encontrado", proveedor=provider.name, consulta=query,
            fuente=best_domain, url_origen=best_url, confidence=best_confidence,
            evidencia=best_evidencia,
            telefono=valor("telefono"), email=valor("email"), web=valor("web"),
            telefono_secundario=valor("telefono_secundario"),
            linkedin_url=valor("linkedin_url"), facebook_url=valor("facebook_url"),
            instagram_url=valor("instagram_url"), twitter_url=valor("twitter_url"),
            detalle=campos,
            duracion_ms=duracion_ms,
            coste_estimado_eur=provider.coste_estimado_por_consulta,
        )

    if not fetched_any and candidates and blocked_by_robots == len(candidates):
        # Every candidate's robots.txt refused the fetch: this attempt never
        # actually examined a page, so it is distinct from "we looked and
        # found no evidence" — surfaced as "omitido", not "no_encontrado".
        return EnrichmentResult(
            estado="omitido", proveedor=provider.name, consulta=query,
            evidencia="robots.txt del sitio candidato bloquea la descarga",
            duracion_ms=duracion_ms, coste_estimado_eur=provider.coste_estimado_por_consulta,
        )
    if not fetched_any and candidates and fetch_errors == len(candidates):
        return EnrichmentResult(
            estado="error", proveedor=provider.name, consulta=query,
            error="No se pudo descargar ningún candidato", duracion_ms=duracion_ms,
            coste_estimado_eur=provider.coste_estimado_por_consulta,
        )
    return EnrichmentResult(
        estado="no_encontrado", proveedor=provider.name, consulta=query,
        duracion_ms=duracion_ms, coste_estimado_eur=provider.coste_estimado_por_consulta,
    )
