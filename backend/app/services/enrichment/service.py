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
from urllib.parse import urljoin, urlparse

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

_last_request_at: dict[str, float] = {}


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
    return True, None


def _build_query(sancionado: Sancionado) -> str:
    location = sancionado.localidad or sancionado.provincia
    return " ".join(part for part in (sancionado.nombre, location) if part).strip()


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
    the caller filters that out before reaching this point."""
    if result.estado == "encontrado":
        if result.telefono:
            sancionado.telefono = sancionado.telefono or result.telefono
        if result.email:
            sancionado.email = sancionado.email or result.email
        sancionado.contacto_estado = "encontrado"
        sancionado.contacto_fuente = result.fuente
        sancionado.contacto_url = result.url_origen
        sancionado.contacto_confidence = result.confidence
    else:
        sancionado.contacto_estado = "no_encontrado"
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

    best: EnrichmentResult | None = None
    blocked_by_robots = 0
    fetch_errors = 0
    fetched_any = False
    with httpx.Client(headers={"User-Agent": "boe-sanciones-enrichment/1.0"}) as client:
        for candidate in candidates:
            domain = urlparse(candidate.url).netloc
            if not _robots_allows(candidate.url, client):
                blocked_by_robots += 1
                continue
            try:
                _respect_rate_limit(domain)
                html = _fetch(client, candidate.url)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", candidate.url, exc)
                fetch_errors += 1
                continue
            fetched_any = True

            pages = [(candidate.url, html)]
            for legal_url in _find_legal_links(html, candidate.url):
                try:
                    _respect_rate_limit(urlparse(legal_url).netloc)
                    pages.append((legal_url, _fetch(client, legal_url)))
                except Exception:
                    continue

            for page_url, page_html in pages:
                outcome = verify_evidence(
                    page_text=page_html, identificador=sancionado.identificador, nombre=sancionado.nombre,
                )
                if outcome.confidence < settings.enrichment_min_confidence:
                    continue
                phones = patterns.find_phones(page_html)
                emails = patterns.find_emails(page_html)
                if not phones and not emails:
                    continue
                candidate_result = EnrichmentResult(
                    estado="encontrado", proveedor=provider.name, consulta=query,
                    fuente=domain, url_origen=page_url, confidence=outcome.confidence,
                    evidencia=outcome.evidencia,
                    telefono=phones[0] if phones else None,
                    email=emails[0] if emails else None,
                    duracion_ms=int((time.monotonic() - started) * 1000),
                    coste_estimado_eur=provider.coste_estimado_por_consulta,
                )
                if best is None or candidate_result.confidence > best.confidence:
                    best = candidate_result

    if best is not None:
        return best

    duracion_ms = int((time.monotonic() - started) * 1000)
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
