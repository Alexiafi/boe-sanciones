"""Shared types for the contact-enrichment cascade.

A ``SearchProvider`` only discovers candidate URLs for a query — it never fetches
or parses a page. Fetching, following "aviso legal"/"contacto" links, regex
extraction and evidence-based verification are provider-agnostic and live in
``service.py`` (the orchestration layer), so every provider gets that behaviour
for free and cannot skip the verification step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchCandidate:
    url: str
    title: str | None = None
    snippet: str | None = None


class SearchProvider(Protocol):
    """Discovers candidate URLs for a query. Read-only; makes no assumption
    about which candidate (if any) actually belongs to the searched entity —
    that judgment is made later, from page content, not from search ranking.
    """

    name: str
    # Whether this provider needs an API key/URL to function. Used by the
    # service layer to give a clear 409 instead of a confusing empty result
    # when a provider is selected but not configured.
    requiere_api_key: bool
    # Informational only, used to log ``coste_estimado_eur`` on each attempt.
    # None of the default providers here are billed per query in the free tiers
    # this session targets.
    coste_estimado_por_consulta: float

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        ...


@dataclass(frozen=True)
class EnrichmentResult:
    """Outcome of one enrichment attempt against one Sancionado."""

    estado: str  # encontrado | no_encontrado | error
    proveedor: str
    consulta: str | None = None
    fuente: str | None = None
    url_origen: str | None = None
    confidence: float = 0.0
    evidencia: str | None = None
    telefono: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    error: str | None = None
    duracion_ms: int | None = None
    coste_estimado_eur: float = 0.0
