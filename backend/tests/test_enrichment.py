"""Contact-enrichment cascade: all network calls are mocked or replaced by the
FixtureProvider. No test in this file may reach a real network — the guard
test below actively enforces that by making ``httpx.Client`` raise if built.
"""

from __future__ import annotations

from datetime import date
import os

import pytest

from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.enriquecimiento import EnriquecimientoIntento
from app.models.sancionado import Sancionado
from app.services.enrichment import service as enrichment_service
from app.services.enrichment.base import SearchCandidate
from app.services.enrichment.providers.fixture import FixtureProvider

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")

EMPRESA_HTML_CON_CIF = """
<html><body>
<p>ACME LOGISTICA SL - CIF B12345678</p>
<p>Contacto: 611222333 - info@acmelogistica.test</p>
<a href="/aviso-legal">Aviso legal</a>
</body></html>
"""

EMPRESA_HTML_SIN_EVIDENCIA = """
<html><body>
<p>Bienvenidos a nuestra web de servicios generales.</p>
<p>Llamanos al 611222333 o escribe a hola@otraempresa.test</p>
</body></html>
"""


def _opportunity(session, *, nombre="Acme Logistica SL", identificador="B12345678", localidad="Sevilla") -> Sancionado:
    document = BoeDocumento(boe_id=f"BOE-2026-ENRICH-{id(object())}", fecha_publicacion=date(2026, 8, 1), titulo="Doc")
    session.add(document)
    session.flush()
    # codigo/origen_clave must be globally unique; derive them from the row's
    # own id (assigned on flush) rather than a hardcoded placeholder, since
    # several tests create more than one opportunity.
    sancionado = Sancionado(
        boe_document_id=document.id, codigo="OP-2026-000000", origen_clave="placeholder",
        nombre=nombre, identificador=identificador, localidad=localidad, tipo_persona="juridica",
    )
    session.add(sancionado)
    session.flush()
    sancionado.codigo = f"OP-2026-{sancionado.id:06d}"
    sancionado.origen_clave = f"enrich-test-{sancionado.id}".ljust(64, "x")[:64]
    session.flush()
    return sancionado


def _enable(monkeypatch, provider="fixture"):
    monkeypatch.setattr(settings, "enrichment_enabled", True)
    monkeypatch.setattr(settings, "enrichment_search_provider", provider)


def test_find_legal_links_follows_aviso_legal_and_contacto():
    """LSSI-CE requires Spanish businesses to publish identity data (incl. CIF)
    under 'aviso legal'/'contacto' — this is why the cascade follows those
    specific links from a homepage rather than treating it as just any link."""
    html = """
    <html><body>
    <a href="/aviso-legal">Aviso Legal</a>
    <a href="/productos">Productos</a>
    <a href="https://otro.test/contacto">Contacto</a>
    </body></html>
    """
    links = enrichment_service._find_legal_links(html, "https://acme.test/")
    assert "https://acme.test/aviso-legal" in links
    assert "https://otro.test/contacto" in links
    assert not any("productos" in link for link in links)


@pytest.mark.integration
def test_evidence_match_persists_contact_with_provenance(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://acmelogistica.test/")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: EMPRESA_HTML_CON_CIF)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "encontrado"
    assert result.confidence == 0.9
    assert sancionado.telefono == "611222333"
    assert sancionado.email == "info@acmelogistica.test"
    assert sancionado.contacto_estado == "encontrado"
    assert sancionado.contacto_fuente == "acmelogistica.test"
    assert sancionado.contacto_url == "https://acmelogistica.test/"
    assert float(sancionado.contacto_confidence) == 0.9

    attempts = session.execute(select(EnriquecimientoIntento)).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].resultado == "encontrado"
    assert attempts[0].evidencia and "B12345678" in attempts[0].evidencia
    session.close()


@pytest.mark.integration
def test_no_evidence_never_writes_a_guessed_contact(monkeypatch, clean_database):
    """A page with a phone number but NO textual evidence tying it to this
    entity must not have that number attributed to the sanctioned party."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session, nombre="Acme Logistica SL", identificador="B12345678")
    session.commit()
    _enable(monkeypatch)

    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://otraempresa.test/")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: EMPRESA_HTML_SIN_EVIDENCIA)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "no_encontrado"
    assert sancionado.telefono is None
    assert sancionado.email is None
    assert sancionado.contacto_estado == "no_encontrado"
    session.close()


@pytest.mark.integration
def test_confidence_below_threshold_is_discarded(monkeypatch, clean_database):
    """Name-only evidence (0.6) must be discarded when the configured minimum
    is stricter than that — no partial credit below the threshold."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session, identificador=None)
    session.commit()
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "enrichment_min_confidence", 0.8)

    html_name_only = """<html><body><p>Acme Logistica SL</p><p>Tel: 611222333</p></body></html>"""
    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://acmelogistica.test/")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: html_name_only)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    result = enrichment_service.enrich_sancionado(session, sancionado)
    assert result.estado == "no_encontrado"
    assert sancionado.telefono is None
    session.close()


@pytest.mark.integration
def test_cache_avoids_a_second_provider_call(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    calls = []

    class CountingProvider(FixtureProvider):
        def buscar(self, query, max_results):
            calls.append(query)
            return super().buscar(query, max_results)

    provider = CountingProvider({"Acme Logistica SL Sevilla": [SearchCandidate(url="https://acmelogistica.test/")]})
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: EMPRESA_HTML_CON_CIF)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()
    # Second attempt on a fresh Sancionado sharing the same query must reuse the cache.
    sancionado2 = _opportunity(session, identificador="B99999999")
    sancionado2.nombre = sancionado.nombre
    sancionado2.localidad = sancionado.localidad
    session.commit()
    enrichment_service.enrich_sancionado(session, sancionado2)
    session.commit()

    assert len(calls) == 1


@pytest.mark.integration
def test_robots_disallow_yields_omitido_not_no_encontrado(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    provider = FixtureProvider({"Acme Logistica SL Sevilla": [SearchCandidate(url="https://acmelogistica.test/")]})
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: False)

    def _fetch_should_not_be_called(client, url):  # pragma: no cover - only on regression
        raise AssertionError("robots.txt disallowed this URL; it must not be fetched")

    monkeypatch.setattr(enrichment_service, "_fetch", _fetch_should_not_be_called)

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "omitido"
    # An omitido attempt must not flip contacto_estado away from "pendiente":
    # it is eligible for a retry, unlike a genuine "no_encontrado".
    assert sancionado.contacto_estado == "pendiente"


@pytest.mark.integration
def test_manual_contact_is_never_overwritten(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    sancionado.telefono = "600000000"
    sancionado.contacto_estado = "manual"
    sancionado.contacto_fuente = "manual"
    session.commit()
    _enable(monkeypatch)

    calls = []

    class CountingProvider(FixtureProvider):
        def buscar(self, query, max_results):
            calls.append(query)
            return []

    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: CountingProvider())

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "omitido"
    assert calls == []  # never even queried the provider
    assert sancionado.telefono == "600000000"
    assert sancionado.contacto_estado == "manual"

    attempts = session.execute(select(EnriquecimientoIntento)).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].resultado == "omitido"


@pytest.mark.integration
def test_disabled_enrichment_never_constructs_http_client(monkeypatch, clean_database):
    """Guard against a future regression reaching the network while disabled —
    same discipline as the session 1 OpenAI-construction guard."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    monkeypatch.setattr(settings, "enrichment_enabled", False)

    def _boom(*args, **kwargs):  # pragma: no cover - only invoked on regression
        raise AssertionError("httpx.Client must not be constructed while enrichment is disabled")

    monkeypatch.setattr(enrichment_service.httpx, "Client", _boom)

    with pytest.raises(enrichment_service.EnrichmentDisabled):
        enrichment_service.enrich_sancionado(session, sancionado)


@pytest.mark.integration
def test_enrichment_available_reports_missing_configuration(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "enrichment_enabled", False)
    available, reason = enrichment_service.enrichment_available()
    assert not available and "ENRICHMENT_ENABLED" in reason

    monkeypatch.setattr(settings, "enrichment_enabled", True)
    monkeypatch.setattr(settings, "enrichment_search_provider", "none")
    available, reason = enrichment_service.enrichment_available()
    assert not available and "ENRICHMENT_SEARCH_PROVIDER" in reason

    monkeypatch.setattr(settings, "enrichment_search_provider", "tavily")
    monkeypatch.setattr(settings, "tavily_api_key", "")
    available, reason = enrichment_service.enrichment_available()
    assert not available and "TAVILY_API_KEY" in reason

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    available, reason = enrichment_service.enrichment_available()
    assert available and reason is None


@pytest.mark.integration
def test_empty_query_is_recorded_without_any_provider_call(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session, nombre=None, localidad=None)
    session.commit()
    _enable(monkeypatch)

    calls = []

    class CountingProvider(FixtureProvider):
        def buscar(self, query, max_results):
            calls.append(query)
            return []

    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: CountingProvider())
    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "no_encontrado"
    assert calls == []
    attempts = session.execute(select(EnriquecimientoIntento)).scalars().all()
    assert len(attempts) == 1
