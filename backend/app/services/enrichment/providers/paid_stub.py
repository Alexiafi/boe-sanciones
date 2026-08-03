"""Documented placeholder for future paid providers (eInforma, Google Places, ...).

Not implemented and not wired into any default configuration — selecting it
raises immediately rather than silently doing nothing, so a misconfiguration is
never mistaken for "no results found". It exists so a future session has a
concrete interface to fill in, matching PLAN.md §12's mention of eInforma as an
optional, explicitly-activated integration.
"""

from __future__ import annotations

from app.services.enrichment.base import SearchCandidate


class PaidProviderStub:
    name = "paid_stub"
    requiere_api_key = True
    coste_estimado_por_consulta = 0.0

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        raise NotImplementedError(
            "Paid enrichment providers (eInforma, Google Places, etc.) are not "
            "integrated in session 2. This stub documents the interface for a "
            "future session; it must be explicitly implemented and enabled."
        )
