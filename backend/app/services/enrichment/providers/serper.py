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
                    # gl/hl bias results to Spanish-language pages from Spain;
                    # without them a Spanish company name returns the English
                    # or international versions of directories (dnb.com,
                    # infoempresa.com/en-in/...) that block scraping.
                    json={"q": query, "num": max_results, "gl": "es", "hl": "es"},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("Serper search failed for query %r", query)
            return []

        # knowledgeGraph/answerBox often carry the company's own website and
        # phone directly; surface them as first-class candidates so the cascade
        # can mine their snippets even before fetching any page.
        extras: list[SearchCandidate] = []
        knowledge_graph = data.get("knowledgeGraph") or {}
        kg_url = knowledge_graph.get("website") or knowledge_graph.get("url")
        if kg_url:
            snippet = " · ".join(
                part for part in (
                    knowledge_graph.get("title"), knowledge_graph.get("type"),
                    knowledge_graph.get("address"), knowledge_graph.get("phone"),
                ) if part
            )
            extras.append(SearchCandidate(url=kg_url, title=knowledge_graph.get("title"), snippet=snippet or None))
        answer_box = data.get("answerBox") or {}
        if answer_box.get("link"):
            extras.append(SearchCandidate(
                url=answer_box["link"], title=answer_box.get("title"),
                snippet=answer_box.get("snippet") or answer_box.get("answer"),
            ))

        organic = [
            SearchCandidate(url=item["link"], title=item.get("title"), snippet=item.get("snippet"))
            for item in data.get("organic", [])
            if item.get("link")
        ]
        seen = {candidate.url for candidate in extras}
        return (extras + [c for c in organic if c.url not in seen])[:max_results]
