"""SearXNG metasearch provider — the recommended zero-marginal-cost default.

SearXNG is self-hosted (no API key, no per-query billing); see the session 2
plan for why the "obvious" free options (Google CSE, Brave Search API) were
verified and ruled out in 2026. Disabled unless ``SEARXNG_URL`` is set.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.enrichment.base import SearchCandidate

logger = logging.getLogger(__name__)


class SearXNGProvider:
    name = "searxng"
    requiere_api_key = False
    coste_estimado_por_consulta = 0.0

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        if not settings.searxng_url:
            logger.warning("SearXNG provider selected but SEARXNG_URL is empty")
            return []
        try:
            with httpx.Client(timeout=settings.enrichment_http_timeout) as client:
                response = client.get(
                    f"{settings.searxng_url.rstrip('/')}/search",
                    params={"q": query, "format": "json"},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("SearXNG search failed for query %r", query)
            return []

        results = data.get("results", [])[:max_results]
        return [
            SearchCandidate(url=item["url"], title=item.get("title"), snippet=item.get("content"))
            for item in results
            if item.get("url")
        ]
