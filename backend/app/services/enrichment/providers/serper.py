"""Serper.dev search provider — cheap fallback (2,500 trial queries, then a low
per-1,000-query rate; verified in the session 2 research). Disabled unless
``SERPER_API_KEY`` is set.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.enrichment.base import SearchCandidate

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"


class SerperProvider:
    name = "serper"
    requiere_api_key = True
    coste_estimado_por_consulta = 0.001  # approximate, see session 2 plan's provider table

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        if not settings.serper_api_key:
            logger.warning("Serper provider selected but SERPER_API_KEY is empty")
            return []
        try:
            with httpx.Client(timeout=settings.enrichment_http_timeout) as client:
                response = client.post(
                    SERPER_URL,
                    headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": max_results},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("Serper search failed for query %r", query)
            return []

        results = data.get("organic", [])[:max_results]
        return [
            SearchCandidate(url=item["link"], title=item.get("title"), snippet=item.get("snippet"))
            for item in results
            if item.get("link")
        ]
