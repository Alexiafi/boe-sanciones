"""Provider registry for the enrichment search step.

Only ``fixture`` is exercised in tests. ``searxng``/``dataforseo``/``serper``/
``tavily`` are real implementations kept disabled by default
(``ENRICHMENT_SEARCH_PROVIDER=none``); activating one is a config change, not
a code change. ``paid_stub`` documents the interface for future paid providers
(eInforma, Google Places) without wiring them in.

Recommended stack, per deep-research-report (14).md (2026-08-03):
``dataforseo`` primary, ``serper`` fallback, ``searxng`` third tier.
Revised after live tests with the client's real cases (2026-10-17): DataForSEO
answered "Internal SE Server Error" to about one query in three and ranked other
companies for a bare CIF, while Serper returned the right company every time at
half the price. With both configured, ``proveedor_google`` uses Serper first and
DataForSEO only when Serper fails.
``tavily`` is NOT recommended — see providers/tavily.py's docstring for the
contractual reason — and should not be selected without written authorization.
"""

from __future__ import annotations

from app.services.enrichment.base import SearchProvider
from app.services.enrichment.providers.dataforseo import DataForSEOProvider
from app.services.enrichment.providers.fixture import FixtureProvider
from app.services.enrichment.providers.paid_stub import PaidProviderStub
from app.services.enrichment.providers.searxng import SearXNGProvider
from app.services.enrichment.providers.serper import SerperProvider
from app.services.enrichment.providers.tavily import TavilyProvider

_REGISTRY: dict[str, type] = {
    "fixture": FixtureProvider,
    "searxng": SearXNGProvider,
    "dataforseo": DataForSEOProvider,
    "tavily": TavilyProvider,
    "serper": SerperProvider,
    "paid_stub": PaidProviderStub,
}


def get_provider(name: str) -> SearchProvider | None:
    """Return an instance of the named provider, or None for "none"/unknown.

    Returning None (rather than raising) lets the service layer treat "no
    provider configured" as a 409 with a clear message instead of a 500.
    """
    provider_cls = _REGISTRY.get(name)
    if provider_cls is None:
        return None
    return provider_cls()


class _ConRespaldo:
    """Primary Google SERP provider with the other one as fallback on error."""

    def __init__(self, principal: SearchProvider, respaldo: SearchProvider) -> None:
        self.principal = principal
        self.respaldo = respaldo
        self.name = principal.name
        self.requiere_api_key = principal.requiere_api_key
        self.coste_estimado_por_consulta = principal.coste_estimado_por_consulta

    def buscar(self, query: str, max_results: int):
        from app.services.enrichment.base import SearchProviderError

        try:
            return self.principal.buscar(query, max_results)
        except SearchProviderError:
            return self.respaldo.buscar(query, max_results)


def proveedor_google(name: str) -> SearchProvider | None:
    """The provider the cascade actually uses for ``name``: for the two Google
    SERP providers, Serper first when its key is set, the other as fallback."""
    from app.config import settings

    if name in ("dataforseo", "serper"):
        serper_ok = bool(settings.serper_api_key)
        dataforseo_ok = bool(settings.dataforseo_login and settings.dataforseo_password)
        if serper_ok and dataforseo_ok:
            return _ConRespaldo(SerperProvider(), DataForSEOProvider())
        if serper_ok:
            return SerperProvider()
    return get_provider(name)


__all__ = ["SearchProvider", "get_provider", "proveedor_google"]
