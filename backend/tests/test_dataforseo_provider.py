"""Unit tests for the DataForSEO provider's response parsing.

Pure unit tests: httpx.Client is replaced by a fake that never opens a socket,
so these need no ephemeral PostgreSQL and no network.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.enrichment.providers import dataforseo as dataforseo_module
from app.services.enrichment.providers.dataforseo import DataForSEOProvider


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json=None):
        return _FakeResponse(_FakeClient.payload)


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "test-login")
    monkeypatch.setattr(settings, "dataforseo_password", "test-password")


def test_parses_organic_results_and_skips_paid_entries(monkeypatch):
    _configure(monkeypatch)
    _FakeClient.payload = {
        "tasks": [{
            "status_code": 20000,
            "status_message": "Ok.",
            "result": [{"items": [
                {"type": "organic", "url": "https://acmelogistica.test/", "title": "Acme", "description": "desc 1"},
                {"type": "paid", "url": "https://ads.test/"},
                {"type": "organic", "url": "https://otra.test/", "title": "Otra", "description": "desc 2"},
            ]}],
        }],
    }
    monkeypatch.setattr(dataforseo_module.httpx, "Client", _FakeClient)

    results = DataForSEOProvider().buscar("Acme Logistica SL Sevilla", 10)

    assert [item.url for item in results] == ["https://acmelogistica.test/", "https://otra.test/"]
    assert results[0].title == "Acme"
    assert results[0].snippet == "desc 1"


def test_failed_task_status_returns_empty_list(monkeypatch):
    _configure(monkeypatch)
    _FakeClient.payload = {"tasks": [{"status_code": 40501, "status_message": "Invalid Field", "result": None}]}
    monkeypatch.setattr(dataforseo_module.httpx, "Client", _FakeClient)

    assert DataForSEOProvider().buscar("consulta cualquiera", 10) == []


def test_missing_credentials_never_constructs_http_client(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "")
    monkeypatch.setattr(settings, "dataforseo_password", "")

    def _boom(*args, **kwargs):  # pragma: no cover - only on regression
        raise AssertionError("httpx.Client must not be constructed without DataForSEO credentials")

    monkeypatch.setattr(dataforseo_module.httpx, "Client", _boom)

    assert DataForSEOProvider().buscar("consulta cualquiera", 10) == []
