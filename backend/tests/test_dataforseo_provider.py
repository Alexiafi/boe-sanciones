"""Unit tests for the DataForSEO provider's response parsing.

Pure unit tests: httpx.Client is replaced by a fake that never opens a socket,
so these need no ephemeral PostgreSQL and no network.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.services.enrichment.base import SearchProviderError
from app.services.enrichment.providers import dataforseo as dataforseo_module
from app.services.enrichment.providers.dataforseo import DataForSEOProvider


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.reason_phrase = "Forbidden" if status_code == 403 else "OK"
        self.request = httpx.Request("POST", dataforseo_module.DATAFORSEO_URL)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Client error {self.status_code}",
                request=self.request,
                response=self,
            )

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
        return _FakeResponse(_FakeClient.payload, getattr(_FakeClient, "status_code", 200))


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "dataforseo_login", "test-login")
    monkeypatch.setattr(settings, "dataforseo_password", "test-password")
    _FakeClient.status_code = 200


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


def test_unverified_account_403_raises_search_provider_error(monkeypatch):
    _configure(monkeypatch)
    _FakeClient.status_code = 403
    _FakeClient.payload = {
        "status_code": 40104,
        "status_message": (
            "Please verify your account before using the API. "
            "You can complete verification in the user panel: https://app.dataforseo.com/ ."
        ),
        "tasks": None,
    }
    monkeypatch.setattr(dataforseo_module.httpx, "Client", _FakeClient)

    with pytest.raises(SearchProviderError, match="verificar la cuenta"):
        DataForSEOProvider().buscar("CIF B02631414", 10)

    _FakeClient.status_code = 200


def test_timeout_raises_search_provider_error(monkeypatch):
    _configure(monkeypatch)

    class _TimeoutClient(_FakeClient):
        def post(self, url, json=None):
            raise httpx.ReadTimeout("The read operation timed out")

    monkeypatch.setattr(dataforseo_module.httpx, "Client", _TimeoutClient)

    with pytest.raises(SearchProviderError, match="no contestó a tiempo"):
        DataForSEOProvider().buscar("Gesconsult, SA, SGIIC", 10)
