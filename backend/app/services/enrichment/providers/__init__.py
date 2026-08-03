"""Provider registry for the enrichment search step.

Only ``fixture`` is exercised in tests. ``searxng``/``dataforseo``/``serper``/
``tavily`` are real implementations kept disabled by default
(``ENRICHMENT_SEARCH_PROVIDER=none``); activating one is a config change, not
a code change. ``paid_stub`` documents the interface for future paid providers
(eInforma, Google Places) without wiring them in.

Recommended stack, per deep-research-report (14).md (2026-08-03):
``dataforseo`` primary, ``serper`` fallback, ``searxng`` third tier.
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


__all__ = ["SearchProvider", "get_provider"]
