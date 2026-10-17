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
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.models.cliente import Cliente
from app.models.enriquecimiento import EnriquecimientoCache, EnriquecimientoIntento
from app.models.sancionado import Sancionado
from app.services.enrichment import patterns
from app.services.enrichment.base import EnrichmentResult, SearchCandidate
from app.services.enrichment.providers import get_provider
from app.services.enrichment.verify import verify as verify_evidence
from app.services.contacto import es_email_institucional, es_telefono_institucional
from app.services.historico.patterns import clave_identidad
from app.services.identidad import compartir_perfil

logger = logging.getLogger(__name__)

# Bounded tree crawl from each SERP candidate: homepage, then "aviso legal"/
# "contacto" (and the same hints one hop deeper). A single attempt must not
# wander the web — depth and page caps are the hard stop.
MAX_CRAWL_DEPTH = 2
MAX_PAGES_PER_CANDIDATE = 8
MAX_LEGAL_LINKS_PER_PAGE = 5
MAX_PAGE_BYTES = 300_000
# Divi/WordPress homepages often exceed this; contact lives in the footer.
_PAGE_HEAD_BYTES = 80_000
_SKIP_HREF_PREFIXES = ("mailto:", "javascript:", "tel:", "#")

# A page that only yielded a website (no phone, email or social profile) is
# not "contacto encontrado" — that was the "encontrado A431…" false positive.
CONTACTO_UTIL = (
    "telefono", "telefono_secundario", "email",
    "linkedin_url", "facebook_url", "instagram_url", "twitter_url",
)

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

# Some Spanish company sites (WordPress/nginx WAF) 403 a custom bot UA and
# even a full Chrome UA, but accept a generic Mozilla/5.0 or httpx's default.
_FETCH_USER_AGENTS = (
    "Mozilla/5.0",
    "python-httpx/0.28.1",
)


def _nombre_es_identificador(nombre: str | None) -> bool:
    return bool(nombre) and bool(_ID_LIKE_RE.fullmatch(nombre.strip().upper()))


def _nombre_vacio(sancionado: Sancionado) -> bool:
    return not sancionado.nombre or _nombre_es_identificador(sancionado.nombre)


def _prefijo_identificador(sancionado: Sancionado) -> str:
    tipo = (sancionado.tipo_identificador or "").upper()
    if tipo in ("DNI", "NIE", "NIF", "CIF"):
        return "DNI" if tipo == "NIF" else tipo
    ident = (sancionado.identificador or "").strip().upper()
    if ident[:1] in "XYZ" and len(ident) == 9:
        return "NIE"
    if ident[:1].isalpha():
        return "CIF"
    return "DNI"


def _build_query(sancionado: Sancionado) -> str:
    """SERP query. A fiscal ID alone is viable: directories (eInforma, InfoCIF)
    resolve CIF/DNI to a razón social in one hop."""
    location = sancionado.localidad or sancionado.provincia
    nombre = None if _nombre_es_identificador(sancionado.nombre) else sancionado.nombre
    identificador = (sancionado.identificador or "").strip() or None
    if identificador is None and _nombre_es_identificador(sancionado.nombre):
        identificador = sancionado.nombre.strip()
    if nombre:
        return " ".join(part for part in (nombre, identificador, location) if part).strip()
    if identificador:
        return " ".join(
            part for part in (_prefijo_identificador(sancionado), identificador, location) if part
        ).strip()
    return ""


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


def _cliente_por_clave(db, clave: str) -> Cliente | None:
    def normalizada(columna):
        return func.regexp_replace(func.upper(columna), r"[\s.\-]", "", "g")

    return db.execute(
        select(Cliente).where((normalizada(Cliente.cif_nif) == clave) | (normalizada(Cliente.dni_nie) == clave))
        .order_by(Cliente.id).limit(1)
    ).scalars().first()


def _harvest_local(db, sancionado: Sancionado) -> dict:
    """Fill identity/contact from what this system already knows about the
    SAME party: its client ficha and its other notices (same DNI/CIF).

    It deliberately never reads the text of the BOE/TEU notice itself: a notice
    is written by an administration, so the only phone numbers and emails in it
    are the administration's own (and a list of many people has no way to say
    which name belongs to which number). Contact for a sanctioned party has to
    come from the web (``_run_cascade``) or from a person."""
    hallado: dict = {}
    clave = clave_identidad(sancionado.identificador)
    if not clave and _nombre_es_identificador(sancionado.nombre):
        clave = clave_identidad(sancionado.nombre)
    if not clave:
        return hallado

    def recoger(origen, fuente: str, mapa: dict[str, str]) -> None:
        for campo_destino, campo_origen in mapa.items():
            valor = getattr(origen, campo_origen, None)
            if valor and campo_destino not in hallado:
                if campo_destino == "telefono" and es_telefono_institucional(valor):
                    continue
                if campo_destino == "email" and es_email_institucional(valor):
                    continue
                hallado[campo_destino] = valor
                if campo_destino in ("telefono", "email"):
                    hallado.setdefault("fuente", fuente)

    cliente = _cliente_por_clave(db, clave)
    if cliente is not None:
        recoger(cliente, "cliente", {
            "nombre": "nombre_razon_social", "localidad": "localidad", "provincia": "provincia",
            "telefono": "telefono", "email": "email",
        })

    hermanas = db.execute(
        select(Sancionado).where(Sancionado.identidad_clave == clave, Sancionado.id != sancionado.id)
        .order_by(Sancionado.id.desc()).limit(5)
    ).scalars().all()
    for hermana in hermanas:
        if hermana.nombre and not _nombre_es_identificador(hermana.nombre):
            hallado.setdefault("nombre", hermana.nombre)
        recoger(hermana, "sancionado", {
            "localidad": "localidad", "provincia": "provincia", "telefono": "telefono", "email": "email",
        })
    if hallado.get("telefono") or hallado.get("email"):
        hallado["evidencia"] = (
            "Contacto ya registrado en la ficha del cliente" if hallado.get("fuente") == "cliente"
            else "Contacto ya registrado en otra notificación del mismo DNI/CIF"
        )
    return hallado


def _apply_harvest_identity(sancionado: Sancionado, hallado: dict) -> None:
    if hallado.get("nombre") and _nombre_vacio(sancionado):
        sancionado.nombre = hallado["nombre"]
    if hallado.get("localidad") and not sancionado.localidad:
        sancionado.localidad = hallado["localidad"]
    if hallado.get("provincia") and not sancionado.provincia:
        sancionado.provincia = hallado["provincia"]


def _result_from_harvest(sancionado: Sancionado, provider, hallado: dict, started: float) -> EnrichmentResult | None:
    if not hallado.get("telefono") and not hallado.get("email"):
        return None
    detalle: dict[str, dict] = {}
    for field in ("telefono", "email"):
        valor = hallado.get(field)
        if valor:
            # No URL: the value comes from this system's own records, and a
            # non-URL must never be rendered as a link (it resolved against the
            # app itself and 404'd).
            detalle[field] = {"valor": valor, "fuente_url": None, "confidence": 0.9}
    return EnrichmentResult(
        estado="encontrado",
        proveedor=provider.name,
        consulta=sancionado.identificador,
        fuente=hallado.get("fuente") or "sancionado",
        url_origen=None,
        confidence=0.9,
        evidencia=hallado.get("evidencia") or "Contacto ya registrado para el mismo DNI/CIF",
        telefono=hallado.get("telefono"),
        email=hallado.get("email"),
        detalle=detalle,
        duracion_ms=int((time.monotonic() - started) * 1000),
    )


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
    # UPSERT rather than get-then-add: two enrichment tasks for the same
    # query can run concurrently (the worker has several processes) and the
    # second INSERT used to fail the whole task with a duplicate-key error.
    db.execute(
        pg_insert(EnriquecimientoCache)
        .values(clave=key, payload=payload, expires_at=expires_at)
        .on_conflict_do_update(
            index_elements=[EnriquecimientoCache.clave], set_={"payload": payload, "expires_at": expires_at},
        )
    )


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


def _trim_page(text: str) -> str:
    """Keep the document head (nav/legal links) and tail (footer contact)."""
    if len(text) <= MAX_PAGE_BYTES:
        return text
    tail = MAX_PAGE_BYTES - _PAGE_HEAD_BYTES
    return text[:_PAGE_HEAD_BYTES] + text[-tail:]


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
def _fetch(client: httpx.Client, url: str) -> str:
    last_error: Exception | None = None
    for index, user_agent in enumerate(_FETCH_USER_AGENTS):
        response = client.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=settings.enrichment_http_timeout,
            follow_redirects=True,
        )
        if response.status_code == 403 and index < len(_FETCH_USER_AGENTS) - 1:
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            last_error = exc
            continue
        return _trim_page(response.text)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def _find_legal_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href, label = match.group(1), re.sub(r"<[^>]+>", " ", match.group(2)).strip().lower()
        if href.lower().startswith(_SKIP_HREF_PREFIXES):
            continue
        haystack = f"{href.lower()} {label}"
        if not any(hint in haystack for hint in patterns.LEGAL_LINK_HINTS):
            continue
        url = _normalise_candidate_url(urljoin(base_url, href))
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links[:MAX_LEGAL_LINKS_PER_PAGE]


def _same_host(url_a: str, url_b: str) -> bool:
    return urlparse(url_a).netloc.lower() == urlparse(url_b).netloc.lower()


def _crawl_contact_pages(client: httpx.Client, start_url: str, start_html: str) -> list[tuple[str, str]]:
    """BFS over contact/legal links, capped by depth and page count.

    The first hop from the SERP candidate may leave the host (a directory
    result pointing at the company's own site). Deeper hops stay on the host
    of the page they were found on, so one attempt cannot crawl the web.
    """
    visited: set[str] = set()
    queue: list[tuple[str, str | None, int]] = [(start_url, start_html, 0)]
    pages: list[tuple[str, str]] = []

    while queue and len(pages) < MAX_PAGES_PER_CANDIDATE:
        url, html, depth = queue.pop(0)
        url = _normalise_candidate_url(url)
        if url in visited:
            continue
        visited.add(url)
        if html is None:
            if not _robots_allows(url, client):
                continue
            try:
                _respect_rate_limit(urlparse(url).netloc)
                html = _fetch(client, url)
            except Exception:
                continue
        pages.append((url, html))
        if depth >= MAX_CRAWL_DEPTH:
            continue
        for link in _find_legal_links(html, url):
            if link in visited:
                continue
            if depth >= 1 and not _same_host(link, url):
                continue
            queue.append((link, None, depth + 1))
    return pages


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
    hallado = _harvest_local(db, sancionado)
    _apply_harvest_identity(sancionado, hallado)
    harvested = _result_from_harvest(sancionado, provider, hallado, started)
    if harvested is not None:
        _record_attempt(db, sancionado.id, harvested)
        _apply_result(sancionado, harvested)
        return harvested

    query = _build_query(sancionado)
    if not query:
        result = EnrichmentResult(
            estado="no_encontrado", proveedor=provider.name, consulta=query,
            evidencia="Sin nombre, identificador ni localidad suficientes para construir una búsqueda",
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
    if result.estado == "encontrado":
        # What was found for one notice is the same person's contact on all
        # the others (and on their client ficha): share it where still blank.
        compartir_perfil(db, sancionado)
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


def _contacto_propio(campos: dict) -> bool:
    """True when contact already comes from the company's own site, not a directory."""
    if campos.get("web"):
        return True
    email = campos.get("email")
    if not email:
        return False
    return not patterns.is_generic_directory(urlparse(email["fuente_url"]).netloc)


def _lookup_candidates(db, provider, query: str) -> tuple[list[SearchCandidate], float]:
    cache_key = _cache_key(provider.name, query)
    cached = _get_cached(db, cache_key)
    if cached is not None:
        return cached, 0.0
    candidates = provider.buscar(query, settings.enrichment_max_pages_per_attempt)
    # Never cache an empty miss: a provider outage (401/403 swallowed as [])
    # would lock the query for ENRICHMENT_CACHE_TTL_DAYS and keep reporting
    # "no encontrado" after the account is fixed.
    if candidates:
        _set_cache(db, cache_key, candidates)
    return candidates, provider.coste_estimado_por_consulta


def _run_cascade(db, sancionado: Sancionado, provider, query: str, started: float) -> EnrichmentResult:
    candidates, coste = _lookup_candidates(db, provider, query)
    consultas = [query]
    coste_total = coste

    if not candidates:
        return EnrichmentResult(
            estado="no_encontrado", proveedor=provider.name, consulta=query,
            duracion_ms=int((time.monotonic() - started) * 1000),
            coste_estimado_eur=coste_total,
        )

    campos: dict[str, dict] = {}
    best_confidence = 0.0
    best_url: str | None = None
    best_domain: str | None = None
    best_evidencia: str | None = None
    blocked_by_robots = 0
    fetch_errors = 0
    fetched_any = False
    razon_descubierta: str | None = None

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

    def menciona_identificador(text: str | None) -> bool:
        """A directory result is only evidence of WHO this party is when its
        own text carries the party's DNI/CIF: a SERP can rank any company that
        merely shares words with the query, and taking its name would label
        the wrong entity."""
        if not text or not sancionado.identificador:
            return False
        return verify_evidence(
            page_text=text, identificador=sancionado.identificador, nombre=None,
        ).confidence >= settings.enrichment_min_confidence

    def remember_razon(*texts: str | None, url: str | None = None) -> None:
        nonlocal razon_descubierta
        if razon_descubierta:
            return
        if not any(menciona_identificador(texto) for texto in texts):
            return
        razon_descubierta = patterns.extract_razon_social(*texts)
        if not razon_descubierta and url:
            razon_descubierta = patterns.razon_from_directory_slug(url)

    def consume(batch: list[SearchCandidate], client: httpx.Client) -> None:
        nonlocal blocked_by_robots, fetch_errors, fetched_any
        for candidate in batch:
            url = _normalise_candidate_url(candidate.url)
            domain = urlparse(url).netloc
            snippet = " ".join(part for part in (candidate.title, candidate.snippet) if part)
            if patterns.is_generic_directory(domain):
                remember_razon(candidate.title, candidate.snippet, url=url)
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
            if patterns.is_generic_directory(domain):
                remember_razon(candidate.title, html[:4_000], url=url)
            for page_url, page_html in _crawl_contact_pages(client, url, html):
                absorb(page_html, page_url)

    with httpx.Client(headers={"User-Agent": _FETCH_USER_AGENTS[0]}) as client:
        consume(candidates, client)
        if not _contacto_propio(campos) and razon_descubierta:
            if _nombre_vacio(sancionado):
                sancionado.nombre = razon_descubierta
            if razon_descubierta.upper() not in query.upper():
                followup = f"{razon_descubierta} contacto"
                extra, extra_coste = _lookup_candidates(db, provider, followup)
                coste_total += extra_coste
                consultas.append(followup)
                if extra:
                    consume(extra, client)

    consulta = " → ".join(consultas)
    duracion_ms = int((time.monotonic() - started) * 1000)
    if any(field in campos for field in CONTACTO_UTIL):
        def valor(field: str) -> str | None:
            dato = campos.get(field)
            return dato["valor"] if dato else None

        return EnrichmentResult(
            estado="encontrado", proveedor=provider.name, consulta=consulta,
            fuente=best_domain, url_origen=best_url, confidence=best_confidence,
            evidencia=best_evidencia,
            telefono=valor("telefono"), email=valor("email"), web=valor("web"),
            telefono_secundario=valor("telefono_secundario"),
            linkedin_url=valor("linkedin_url"), facebook_url=valor("facebook_url"),
            instagram_url=valor("instagram_url"), twitter_url=valor("twitter_url"),
            detalle=campos,
            duracion_ms=duracion_ms,
            coste_estimado_eur=coste_total,
        )

    if not fetched_any and candidates and blocked_by_robots == len(candidates):
        # Every candidate's robots.txt refused the fetch: this attempt never
        # actually examined a page, so it is distinct from "we looked and
        # found no evidence" — surfaced as "omitido", not "no_encontrado".
        return EnrichmentResult(
            estado="omitido", proveedor=provider.name, consulta=consulta,
            evidencia="robots.txt del sitio candidato bloquea la descarga",
            duracion_ms=duracion_ms, coste_estimado_eur=coste_total,
        )
    if not fetched_any and candidates and fetch_errors == len(candidates):
        return EnrichmentResult(
            estado="error", proveedor=provider.name, consulta=consulta,
            error="No se pudo descargar ningún candidato", duracion_ms=duracion_ms,
            coste_estimado_eur=coste_total,
        )
    return EnrichmentResult(
        estado="no_encontrado", proveedor=provider.name, consulta=consulta,
        duracion_ms=duracion_ms, coste_estimado_eur=coste_total,
    )
