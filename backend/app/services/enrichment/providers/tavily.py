"""Tavily search provider — managed alternative with a no-card-required free tier
(1,000 credits/month, verified in the session 2 research). Disabled unless
``TAVILY_API_KEY`` is set.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.enrichment.base import SearchCandidate

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


class TavilyProvider:
    name = "tavily"
    requiere_api_key = True
    coste_estimado_por_consulta = 0.0  # informational: within the free monthly credit

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        if not settings.tavily_api_key:
            logger.warning("Tavily provider selected but TAVILY_API_KEY is empty")
            return []
        try:
            with httpx.Client(timeout=settings.enrichment_http_timeout) as client:
                response = client.post(
                    TAVILY_URL,
                    json={"api_key": settings.tavily_api_key, "query": query, "max_results": max_results},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("Tavily search failed for query %r", query)
            return []

        results = data.get("results", [])[:max_results]
        return [
            SearchCandidate(url=item["url"], title=item.get("title"), snippet=item.get("content"))
            for item in results
            if item.get("url")
        ]
