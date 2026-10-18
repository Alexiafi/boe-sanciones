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
from dataclasses import asdict, replace
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
from app.services.enrichment.providers import get_provider, proveedor_google
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


def _identificador_completo(sancionado: Sancionado) -> str | None:
    ident = (sancionado.identificador or "").strip()
    if not ident and _nombre_es_identificador(sancionado.nombre):
        ident = sancionado.nombre.strip()
    return clave_identidad(ident)


def _nombre_util(sancionado: Sancionado) -> str | None:
    if _nombre_vacio(sancionado):
        return None
    nombre = sancionado.nombre.strip()
    return None if clave_identidad(nombre) else nombre


def _es_empresa(sancionado: Sancionado) -> bool:
    """A company: CIF, or (without a complete document) a name with a legal
    form or a row typed as legal person. A DNI/NIE is always a person."""
    clave = _identificador_completo(sancionado)
    if clave:
        return clave[0].isalpha() and clave[0] not in "XYZ"
    nombre = _nombre_util(sancionado)
    return bool(patterns.forma_de_nombre(nombre)) or (sancionado.tipo_persona or "").lower() == "juridica"


def _build_query(sancionado: Sancionado) -> str:
    """First SERP query.

    Companies: with a name, "<razón social> telefono" brings the directory
    snippets that carry the number ("El teléfono de MOLDES DIAZ SA es…");
    without one, the bare CIF ranks the records of exactly that company —
    "CIF B54866371" or adding the town made Google return other companies
    (checked live on 2026-10-17). People keep name + document + town."""
    nombre = _nombre_util(sancionado)
    clave = _identificador_completo(sancionado)
    if _es_empresa(sancionado):
        if nombre:
            return f"{nombre} telefono"
        return clave or ""
    location = sancionado.localidad or sancionado.provincia
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
    provider = proveedor_google(name) if name in ("dataforseo", "serper") else get_provider(name)
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

    nombre_antes = sancionado.nombre
    try:
        result = _run_cascade(db, sancionado, provider, query, started)
        result = _descartar_contacto_compartido(db, sancionado, result)
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
    if result.estado == "encontrado" or sancionado.nombre != nombre_antes:
        # What was found for one notice (contact, or the razón social of a
        # notice that only had the CIF) is the same party's on all the others
        # and on their client ficha: share it where still blank.
        compartir_perfil(db, sancionado)
    return result


# A phone/email already attached to this many OTHER parties is not this one's:
# a directory's or an office's line that slipped through (0016 used 3 parties).
OTRAS_IDENTIDADES_MAX = 2


def _otras_identidades_con(db, campo: str, valor: str, clave_propia: str | None) -> int:
    if campo.startswith("telefono"):
        nacional = patterns.national_digits(valor)
        if not nacional:
            return 0

        def digitos(columna):
            return func.right(func.regexp_replace(columna, r"\D", "", "g"), 9)

        condicion = (digitos(Sancionado.telefono) == nacional) | (digitos(Sancionado.telefono_secundario) == nacional)
    else:
        condicion = func.lower(Sancionado.email) == valor.strip().lower()
    consulta = select(func.count(func.distinct(Sancionado.identidad_clave))).where(
        condicion, Sancionado.identidad_clave.is_not(None),
    )
    if clave_propia:
        consulta = consulta.where(Sancionado.identidad_clave != clave_propia)
    return int(db.execute(consulta).scalar() or 0)


def _descartar_contacto_compartido(db, sancionado: Sancionado, result: EnrichmentResult) -> EnrichmentResult:
    """Drop a found phone/email that other parties already carry."""
    if result.estado != "encontrado" or db is None:
        return result
    clave = clave_identidad(sancionado.identificador)
    detalle = dict(result.detalle or {})
    descartados = []
    for campo in ("telefono", "telefono_secundario", "email"):
        dato = detalle.get(campo)
        if dato and _otras_identidades_con(db, campo, dato["valor"], clave) >= OTRAS_IDENTIDADES_MAX:
            detalle.pop(campo)
            descartados.append(dato["valor"])
    if not descartados:
        return result
    if "telefono" not in detalle and "telefono_secundario" in detalle:
        detalle["telefono"] = detalle.pop("telefono_secundario")
    evidencia = f"Descartado por figurar ya en otras empresas: {', '.join(descartados)}"
    if not any(campo in detalle for campo in CONTACTO_UTIL):
        return replace(
            result, estado="no_encontrado", fuente=None, url_origen=None, confidence=0.0, evidencia=evidencia,
            telefono=None, telefono_secundario=None, email=None, detalle=None,
        )

    def valor(campo: str) -> str | None:
        return (detalle.get(campo) or {}).get("valor")

    return replace(
        result, detalle=detalle, telefono=valor("telefono"), telefono_secundario=valor("telefono_secundario"),
        email=valor("email"), evidencia=f"{result.evidencia or ''} · {evidencia}".strip(" ·"),
    )


# Support a phone/email needs before it is written: one page carrying the
# party's own DNI/CIF next to it (0.9), or two independent pages naming the
# party by its full razón social (2 × 0.6), or its own website (0.6 + 0.3).
SOPORTE_MINIMO_CONTACTO = 0.9
SOPORTE_MINIMO_PERFIL = 0.6  # website / social profile of the party itself
PESO_SITIO_PROPIO = 0.3
MAX_RESULTADOS_SERP = 10
MAX_SITIOS_PROPIOS = 3  # own-website entry pages per search, crawled to contacto/aviso legal


def _dominio(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain


class _Votos:
    """Per-field tally of candidate values: each website counts once per value,
    so the same number on eInforma, Axesor and El Economista outweighs a number
    seen once."""

    def __init__(self) -> None:
        self.datos: dict[str, dict[str, dict]] = {}
        # Domains proven to be the party's own website: a page there carries its
        # CIF or its full razón social WITH the same legal form.
        self.sitios_confirmados: set[str] = set()
        # Domains that show this name with another legal form: a homonym, never the party's.
        self.sitios_descartados: set[str] = set()

    def anadir(self, campo: str, valor: str, url: str, confidence: float, peso: float, *, propio: bool = False) -> None:
        clave = patterns.national_digits(valor) if campo == "telefono" else valor.strip().lower().rstrip("/")
        if not clave:
            return
        entrada = self.datos.setdefault(campo, {}).get(clave)
        if entrada is None:
            entrada = {
                "valor": valor.strip(), "fuente_url": url, "confidence": confidence, "peso": 0.0,
                "dominios": set(), "dominios_propios": set(),
            }
            self.datos[campo][clave] = entrada
        dominio = _dominio(url)
        if propio:
            entrada["dominios_propios"].add(dominio)
        if confidence > entrada["confidence"]:
            entrada.update(valor=valor.strip(), fuente_url=url, confidence=confidence)
        if dominio in entrada["dominios"]:
            return
        entrada["dominios"].add(dominio)
        entrada["peso"] += peso

    def _peso(self, entrada: dict) -> float:
        if entrada["dominios_propios"] and entrada["dominios_propios"] <= self.sitios_descartados:
            return 0.0
        confirmados = self.sitios_confirmados - self.sitios_descartados
        bonus = PESO_SITIO_PROPIO if entrada["dominios_propios"] & confirmados else 0.0
        return entrada["peso"] + bonus

    def mejores(self, campo: str, minimo: float) -> list[dict]:
        filas = [e for e in self.datos.get(campo, {}).values() if self._peso(e) >= minimo - 1e-9]
        return sorted(filas, key=lambda e: (-self._peso(e), -e["confidence"]))

    def soporte(self, campo: str) -> float:
        filas = self.datos.get(campo, {}).values()
        return max((self._peso(e) for e in filas), default=0.0)

    def campos(self) -> dict[str, dict]:
        def fila(e: dict) -> dict:
            return {"valor": e["valor"], "fuente_url": e["fuente_url"], "confidence": e["confidence"]}

        resultado: dict[str, dict] = {}
        telefonos = self.mejores("telefono", SOPORTE_MINIMO_CONTACTO)
        if telefonos:
            resultado["telefono"] = fila(telefonos[0])
        if len(telefonos) > 1:
            resultado["telefono_secundario"] = fila(telefonos[1])
        emails = self.mejores("email", SOPORTE_MINIMO_CONTACTO)
        if emails:
            resultado["email"] = fila(emails[0])
        for campo in ("web", "linkedin_url", "facebook_url", "instagram_url", "twitter_url"):
            # Taken from a website only when that website is proven to be the
            # party's; a profile that is itself a search result needs its name.
            filas = [
                e for e in self.mejores(campo, SOPORTE_MINIMO_PERFIL)
                if not e["dominios_propios"] or e["dominios_propios"] & (self.sitios_confirmados - self.sitios_descartados)
            ]
            if filas:
                resultado[campo] = fila(filas[0])
        return resultado


def _evidencia(texto: str, clave: str | None, nombre: str | None) -> tuple[float, str | None]:
    """0.9 when the party's complete DNI/CIF is on the text, 0.6 when its full
    razón social is (as a whole name, not inside a longer one), else 0."""
    if clave and any(c == clave for _, _, c in patterns.identificadores_en_texto(texto)):
        return 0.9, f"Identificador {clave} encontrado en la página"
    if nombre and patterns.menciona_nombre(texto, nombre):
        return 0.6, f"Nombre/razón social '{nombre}' encontrado en la página"
    return 0.0, None


def _lookup_candidates(db, provider, query: str) -> tuple[list[SearchCandidate], float]:
    cache_key = _cache_key(provider.name, query)
    cached = _get_cached(db, cache_key) if db is not None else None
    if cached is not None:
        return cached, 0.0
    candidates = provider.buscar(query, max(settings.enrichment_max_pages_per_attempt, MAX_RESULTADOS_SERP))
    # Never cache an empty miss: a provider outage (401/403 swallowed as [])
    # would lock the query for ENRICHMENT_CACHE_TTL_DAYS and keep reporting
    # "no encontrado" after the account is fixed.
    if candidates and db is not None:
        _set_cache(db, cache_key, candidates)
    return candidates, provider.coste_estimado_por_consulta


def _titulo_html(html: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _run_cascade(db, sancionado: Sancionado, provider, query: str, started: float) -> EnrichmentResult:
    """Search -> attribute -> vote.

    1. First query (``_build_query``). Results whose title/snippet carry the
       party's CIF give its razón social when the notice had none.
    2. Every snippet, and the pages of the results that name the party, are
       read; a phone/email counts only when it sits next to the party's own
       CIF or full razón social (``patterns.contacto_cercano``) — never the
       directory's own line, another company's sidebar entry or an
       administration's office. Pages of the party's own website are crawled
       to "contacto"/"aviso legal".
    3. Second query when the first did not settle the phone: "<razón social>
       telefono" after a bare-CIF search, or the bare CIF after a name search.
    4. A value is written only with enough independent support (see
       ``SOPORTE_MINIMO_CONTACTO``)."""
    clave = _identificador_completo(sancionado)
    identificador = sancionado.identificador or clave
    votos = _Votos()
    consultas: list[str] = []
    coste_total = 0.0
    paginas_leidas: set[str] = set()
    razones: list[str] = []
    estado = {
        "best_confidence": 0.0, "best_url": None, "best_evidencia": None,
        "robots": 0, "errores": 0, "leidas": 0, "candidatos": 0,
    }

    empresa = _es_empresa(sancionado)

    def nombre_actual() -> str | None:
        return _nombre_util(sancionado)

    def absorb(raw: str, url: str, *, es_snippet: bool, titulo: str | None = None) -> None:
        domain = _dominio(url)
        directorio = patterns.parece_directorio(url, identificador)
        visible = patterns.texto_visible(raw, sin_marco=directorio and not es_snippet)
        nombre = nombre_actual()
        if not directorio and patterns.dominio_parecido(domain, nombre) and patterns.forma_distinta_en(visible, nombre):
            # The same name with another legal form: a homonym (checked before the
            # evidence threshold — such a page has no evidence for THIS company).
            votos.sitios_descartados.add(domain)
        confidence, evidencia = _evidencia(visible, clave, nombre)
        if confidence < settings.enrichment_min_confidence:
            return
        if confidence > estado["best_confidence"]:
            estado.update(best_confidence=confidence, best_url=url, best_evidencia=evidencia)
        # The candidate URL itself may be the party's social profile (a company's
        # LinkedIn is a /company/ page; /in/ is a person's).
        for field, urls in patterns.find_social(url).items():
            if field == "linkedin_url" and empresa and "/in/" in urls[0]:
                continue
            if patterns.perfil_parecido(urls[0], nombre, None):
                votos.anadir(field, urls[0], url, confidence, confidence)
        if patterns.is_non_entity_site(domain):
            return
        if not directorio and patterns.parece_pagina_oficial(visible, identificador):
            return
        propio = not directorio and patterns.dominio_parecido(domain, nombre)
        if propio and domain not in votos.sitios_descartados and (
            confidence >= 0.9 or patterns.menciona_nombre_con_forma(visible, nombre)
            or patterns.dominio_es_el_nombre(domain, nombre)
        ):
            votos.sitios_confirmados.add(domain)
        telefonos, emails = patterns.contacto_cercano(visible, identificador, nombre)
        if propio and not es_snippet:
            # On the party's own site the header/footer contact is theirs.
            telefonos = telefonos or patterns.find_phones(raw)
            emails = emails or patterns.find_emails(raw)
        telefonos = [patterns.telefono_presentable(t) for t in telefonos if not patterns.es_telefono_de_organismo(t)]
        emails = [
            e for e in emails
            if not es_email_institucional(e) and not (directorio and patterns.email_del_sitio(e, domain))
            and not patterns.is_generic_directory(e.rpartition("@")[2])
        ]
        # The own-site bonus is granted at the end, only if some page of that
        # domain proved it belongs to the party (see _Votos.sitios_confirmados).
        peso = confidence
        if (
            directorio and confidence < 0.9 and titulo
            and patterns.is_generic_directory(domain) and patterns.menciona_nombre_con_forma(titulo, nombre)
        ):
            # A company-data directory's record whose TITLE is exactly this razón
            # social with its legal form: the record of this company (razones
            # sociales are unique in Spain). Live: Páginas Amarillas, Empresite.
            peso = 0.9
        for posicion, telefono in enumerate(telefonos[:2]):
            votos.anadir("telefono", telefono, url, confidence, peso if posicion == 0 else peso / 2, propio=propio)
        if emails:
            votos.anadir("email", emails[0], url, confidence, peso, propio=propio)
        if propio and not es_snippet:
            for field, urls in patterns.find_social(raw).items():
                # Theme/agency footers link THEIR profiles ("artbees"): only the party's own.
                propios = [
                    u for u in urls
                    if patterns.perfil_parecido(u, nombre, domain) and not (empresa and "/in/" in u)
                ]
                if propios:
                    votos.anadir(field, propios[0], url, confidence, peso, propio=True)
            votos.anadir("web", f"{urlparse(url).scheme}://{urlparse(url).netloc}", url, confidence, peso, propio=True)

    def descubrir_razon(*textos: str | None, titulo: str | None = None, url: str | None = None) -> None:
        if url and not patterns.parece_directorio(url, identificador):
            # Outside a directory only a result TITLE is read ('X SL - Inicio'):
            # the text of a privacy policy is a sentence, not a name.
            textos = (titulo,)
        if not clave or not any(
            texto and any(c == clave for _, _, c in patterns.identificadores_en_texto(texto)) for texto in textos
        ):
            return
        razon = patterns.razon_de_titulo(titulo)
        if not razon and not (url and not patterns.parece_directorio(url, identificador)):
            razon = patterns.extract_razon_social(*textos)
        razon = patterns.limpiar_razon(razon)
        if razon and not clave_identidad(razon) and patterns.razon_valida(razon):
            razones.append(razon)
            if _nombre_vacio(sancionado):
                sancionado.nombre = razon

    def examinar(batch: list[SearchCandidate], client: httpx.Client) -> None:
        estado["candidatos"] += len(batch)
        for candidate in batch:
            url = _normalise_candidate_url(candidate.url)
            texto_serp = " | ".join(part for part in (candidate.title, candidate.snippet) if part)
            descubrir_razon(candidate.title, candidate.snippet, titulo=candidate.title, url=url)
            if texto_serp:
                absorb(texto_serp, url, es_snippet=True, titulo=candidate.title)
        # Pages worth opening: the party's own website first (its own budget:
        # directories read for the first search must not use it up), then the
        # records that name the party by CIF or full name. Pages about other
        # companies are not read.
        nombre = nombre_actual()
        propias, otras = [], []
        for candidate in batch:
            url = _normalise_candidate_url(candidate.url)
            domain = _dominio(url)
            if url in paginas_leidas or patterns.is_non_entity_site(domain):
                continue
            if not patterns.parece_directorio(url, identificador) and patterns.dominio_parecido(domain, nombre):
                propias.append(url)
                continue
            texto_serp = " ".join(part for part in (candidate.title, candidate.snippet, url) if part)
            if _evidencia(texto_serp, clave, nombre)[0] > 0 or (clave and clave in patterns.clave_compacta(url)):
                otras.append(url)
        # Own-site pages that ARE the legal/contact/privacy page go first.
        propias.sort(key=lambda u: not any(h in u.lower() for h in patterns.LEGAL_LINK_HINTS))
        for url in propias[:MAX_SITIOS_PROPIOS] + otras:
            es_propia = url in propias
            if not es_propia and estado["leidas"] >= settings.enrichment_max_pages_per_attempt:
                break
            if url in paginas_leidas:
                continue
            domain = _dominio(url)
            paginas_leidas.add(url)
            if not _robots_allows(url, client):
                estado["robots"] += 1
                continue
            try:
                _respect_rate_limit(domain)
                html = _fetch(client, url)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", url, exc)
                estado["errores"] += 1
                continue
            if not es_propia:
                estado["leidas"] += 1
            if patterns.parece_directorio(url, identificador):
                descubrir_razon(patterns.texto_visible(html)[:6_000], titulo=_titulo_html(html))
                absorb(html, url, es_snippet=False, titulo=_titulo_html(html))
                continue
            for page_url, page_html in _crawl_contact_pages(client, url, html):
                paginas_leidas.add(page_url)
                absorb(page_html, page_url, es_snippet=False)

    def buscar(consulta: str, client: httpx.Client) -> None:
        nonlocal coste_total
        if not consulta or consulta in consultas:
            return
        candidates, coste = _lookup_candidates(db, provider, consulta)
        coste_total += coste
        consultas.append(consulta)
        examinar(candidates, client)

    with httpx.Client(headers={"User-Agent": _FETCH_USER_AGENTS[0]}) as client:
        buscar(query, client)
        if _es_empresa(sancionado) and votos.soporte("telefono") < SOPORTE_MINIMO_CONTACTO:
            nombre = nombre_actual()
            if clave and query == clave and nombre:
                buscar(f"{nombre} telefono", client)
            elif clave and query != clave:
                buscar(clave, client)

    campos = votos.campos()
    consulta = " → ".join(consultas)
    duracion_ms = int((time.monotonic() - started) * 1000)
    if any(field in campos for field in CONTACTO_UTIL):
        def valor(field: str) -> str | None:
            dato = campos.get(field)
            return dato["valor"] if dato else None

        principal = campos.get("telefono") or campos.get("email") or next(iter(campos.values()))
        return EnrichmentResult(
            estado="encontrado", proveedor=provider.name, consulta=consulta,
            fuente=_dominio(principal["fuente_url"]), url_origen=principal["fuente_url"],
            confidence=principal["confidence"], evidencia=estado["best_evidencia"],
            telefono=valor("telefono"), email=valor("email"), web=valor("web"),
            telefono_secundario=valor("telefono_secundario"),
            linkedin_url=valor("linkedin_url"), facebook_url=valor("facebook_url"),
            instagram_url=valor("instagram_url"), twitter_url=valor("twitter_url"),
            detalle=campos,
            duracion_ms=duracion_ms,
            coste_estimado_eur=coste_total,
        )

    if estado["candidatos"] == 0:
        return EnrichmentResult(
            estado="no_encontrado", proveedor=provider.name, consulta=consulta,
            duracion_ms=duracion_ms, coste_estimado_eur=coste_total,
        )
    if estado["leidas"] == 0 and estado["robots"] and estado["robots"] == len(paginas_leidas):
        # Every page worth reading refused the fetch in robots.txt: this attempt
        # never examined a page, which is distinct from "looked and found nothing".
        return EnrichmentResult(
            estado="omitido", proveedor=provider.name, consulta=consulta,
            evidencia="robots.txt del sitio candidato bloquea la descarga",
            duracion_ms=duracion_ms, coste_estimado_eur=coste_total,
        )
    # Pages that refuse the download (403 from einforma, axesor…) are the normal
    # case, not an error: the search ran and its results were read.
    evidencia = None
    if estado["errores"] and estado["leidas"] == 0:
        evidencia = "Los directorios con su ficha no dejan descargarla y los resultados no traen su teléfono"
    return EnrichmentResult(
        estado="no_encontrado", proveedor=provider.name, consulta=consulta, evidencia=evidencia,
        duracion_ms=duracion_ms, coste_estimado_eur=coste_total,
    )
