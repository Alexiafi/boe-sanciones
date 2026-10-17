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
import time

import httpx

from app.config import settings
from app.services.enrichment.base import SearchCandidate, SearchProviderError

logger = logging.getLogger(__name__)

DATAFORSEO_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
# Live SERP is a Google round-trip; 10s (the page-fetch timeout) routinely
# cuts the request off and used to be swallowed as "no encontrado".
DATAFORSEO_TIMEOUT = 45.0
DATAFORSEO_REINTENTOS = 2


def _error_message(exc: httpx.HTTPStatusError) -> str:
    payload: dict = {}
    try:
        payload = exc.response.json() or {}
    except Exception:
        payload = {}
    api_message = (payload.get("status_message") or "").strip()
    api_code = payload.get("status_code")
    if api_code == 40104 or "verify your account" in api_message.lower():
        suffix = f" {api_message}" if api_message else ""
        return (
            "DataForSEO exige verificar la cuenta antes de usar la API SERP. "
            "Entra en https://app.dataforseo.com/ y completa la verificación."
            + suffix
        )
    if exc.response.status_code in (401, 403):
        suffix = f" {api_message}" if api_message else ""
        return (
            f"DataForSEO rechazó la petición (HTTP {exc.response.status_code}). "
            "Revisa el API login/password en https://app.dataforseo.com/api-access "
            "(no uses la contraseña del panel)."
            + suffix
        )
    return f"DataForSEO HTTP {exc.response.status_code}: {api_message or exc.response.reason_phrase}"


class DataForSEOProvider:
    name = "dataforseo"
    requiere_api_key = True
    coste_estimado_por_consulta = 0.002  # Live mode, depth=10; see provider table in the research report

    def buscar(self, query: str, max_results: int, _reintento: int = 0) -> list[SearchCandidate]:
        if not settings.dataforseo_login or not settings.dataforseo_password:
            logger.warning("DataForSEO provider selected but login/password are not configured")
            return []
        try:
            with httpx.Client(
                timeout=DATAFORSEO_TIMEOUT,
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
        except httpx.TimeoutException as exc:
            logger.exception("DataForSEO search timed out for query %r", query)
            raise SearchProviderError(
                "DataForSEO no contestó a tiempo. La búsqueda en Google suele tardar "
                "varios segundos; reintenta el enriquecimiento."
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.exception("DataForSEO search failed for query %r", query)
            raise SearchProviderError(_error_message(exc)) from exc
        except Exception as exc:
            logger.exception("DataForSEO search failed for query %r", query)
            raise SearchProviderError(f"DataForSEO falló: {type(exc).__name__}") from exc

        tasks = data.get("tasks") or []
        if not tasks or tasks[0].get("status_code") != 20000:
            mensaje = tasks[0].get("status_message") if tasks else "no tasks"
            logger.warning("DataForSEO task did not complete: %s", mensaje)
            # "Internal SE Server Error" comes and goes (live test 2026-10-17: about
            # one query in five). A failed search is not "nothing found": retry,
            # then report it as an error so the party can be searched again.
            if _reintento < DATAFORSEO_REINTENTOS:
                time.sleep(1.5 * (_reintento + 1))
                return self.buscar(query, max_results, _reintento=_reintento + 1)
            raise SearchProviderError(f"DataForSEO no completó la búsqueda: {mensaje}")
        results = tasks[0].get("result") or []
        items = results[0].get("items") if results else []
        organic = [item for item in (items or []) if item.get("type") == "organic"]
        return [
            SearchCandidate(url=item["url"], title=item.get("title"), snippet=item.get("description"))
            for item in organic[:max_results]
            if item.get("url")
        ]
