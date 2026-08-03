"""Deterministic, network-free provider used in tests and local development.

Looks up canned results from a local mapping keyed by exact query string. Never
makes a network call. A query with no matching fixture returns an empty list,
which the orchestration layer correctly treats as "nothing discovered" — not an
error, not a guess.
"""

from __future__ import annotations

from app.services.enrichment.base import SearchCandidate


class FixtureProvider:
    name = "fixture"
    requiere_api_key = False
    coste_estimado_por_consulta = 0.0

    def __init__(self, fixtures: dict[str, list[SearchCandidate]] | None = None):
        self._fixtures = fixtures or {}

    def buscar(self, query: str, max_results: int) -> list[SearchCandidate]:
        return list(self._fixtures.get(query, []))[:max_results]
