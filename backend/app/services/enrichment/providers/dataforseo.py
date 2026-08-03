"""DataForSEO Google Organic SERP API — recommended primary provider.

Chosen over the alternatives researched on 2026-08-03
(deep-research-report (14).md): a pure SERP API (real organic URLs, not an
LLM-summarized answer), effective cost of ~$0.0006-0.002 per query, and a
prepaid balance that never expires (vs. Serper's 6-month credit expiry).
Uses the "Live Advanced" endpoint — one synchronous POST per query — rather
than the cheaper "Standard" queue mode, to keep this provider a drop-in
``SearchProvider`` with no polling; Standard mode could be added later for
batch runs if per-query cost becomes material at higher volume.

Disabled unless both ``DATAFORSEO_LOGIN`` and ``DATAFORSEO_PASSWORD`` are set.
Authentication is HTTP Basic with the login/password from the DataForSEO
dashboard (NOT a single API key). Requires a funded prepaid balance — the
account itself has a $50 minimum top-up — before it returns real results.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.enrichment.base import SearchCandidate

logger = logging.getLogger(__name__)

DATAFORSEO_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"


class DataForSEOProvider:
    name = "dataforseo"
    requiere_api_key = True
    coste_estimado_por_consulta = 0.002  # Live mode, depth=10; see provider table in the research report

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        if not settings.dataforseo_login or not settings.dataforseo_password:
            logger.warning("DataForSEO provider selected but login/password are not configured")
            return []
        try:
            with httpx.Client(
                timeout=settings.enrichment_http_timeout,
                auth=(settings.dataforseo_login, settings.dataforseo_password),
            ) as client:
                response = client.post(
                    DATAFORSEO_URL,
                    json=[{
                        "keyword": query,
                        "location_name": settings.dataforseo_location_name,
                        "language_code": settings.dataforseo_language_code,
                        "device": "desktop",
                        "depth": max(max_results, 10),
                    }],
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.exception("DataForSEO search failed for query %r", query)
            return []

        tasks = data.get("tasks") or []
        if not tasks or tasks[0].get("status_code") != 20000:
            logger.warning("DataForSEO task did not complete: %s", tasks[0].get("status_message") if tasks else "no tasks")
            return []
        results = tasks[0].get("result") or []
        items = results[0].get("items") if results else []
        organic = [item for item in (items or []) if item.get("type") == "organic"]
        return [
            SearchCandidate(url=item["url"], title=item.get("title"), snippet=item.get("description"))
            for item in organic[:max_results]
            if item.get("url")
        ]
