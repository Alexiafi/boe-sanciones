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
from app.models.enriquecimiento import EnriquecimientoCache, EnriquecimientoIntento
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
    session.close()


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
    session.close()


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
    session.close()


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
    session.close()


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

    monkeypatch.setattr(settings, "enrichment_search_provider", "dataforseo")
    monkeypatch.setattr(settings, "dataforseo_login", "")
    monkeypatch.setattr(settings, "dataforseo_password", "")
    available, reason = enrichment_service.enrichment_available()
    assert not available and "DATAFORSEO" in reason

    monkeypatch.setattr(settings, "dataforseo_login", "login")
    monkeypatch.setattr(settings, "dataforseo_password", "password")
    available, reason = enrichment_service.enrichment_available()
    assert available and reason is None

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
    session.close()


@pytest.mark.integration
def test_snippet_contact_survives_page_fetch_failure(monkeypatch, clean_database):
    """Directories like dnb.com 403 our fetches, but the provider's snippet
    already carries CIF + phone + email — that evidence must still be used."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    candidate = SearchCandidate(
        url="https://empresite.eleconomista.es/ACME.html",
        title="Acme Logistica SL - Teléfono y dirección",
        snippet="Su teléfono es 611222333 y su correo es info@acmelogistica.test. CIF B12345678.",
    )
    provider = FixtureProvider({"Acme Logistica SL Sevilla": [candidate]})
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)

    def _fetch_403(client, url):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(enrichment_service, "_fetch", _fetch_403)

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "encontrado"
    assert sancionado.telefono == "611222333"
    assert sancionado.email == "info@acmelogistica.test"
    assert sancionado.contacto_detalle["telefono"]["fuente_url"] == candidate.url
    assert sancionado.contacto_detalle["email"]["fuente_url"] == candidate.url
    # A directory snippet must not become the company's own website.
    assert sancionado.web is None
    session.close()


@pytest.mark.integration
def test_social_links_and_web_stored_with_per_field_provenance(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    html = """
    <html><body>
    <p>ACME LOGISTICA SL - CIF B12345678</p>
    <p>Contacto: 611222333 - info@acmelogistica.test</p>
    <a href="https://es.linkedin.com/company/acme-logistica">LinkedIn</a>
    <a href="https://www.instagram.com/acmelogistica/">Instagram</a>
    </body></html>
    """
    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://acmelogistica.test/")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: html)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "encontrado"
    assert sancionado.web == "https://acmelogistica.test"
    assert sancionado.linkedin_url == "https://es.linkedin.com/company/acme-logistica"
    assert sancionado.instagram_url == "https://www.instagram.com/acmelogistica"
    detalle = sancionado.contacto_detalle
    assert detalle["telefono"]["fuente_url"] == "https://acmelogistica.test/"
    assert detalle["linkedin_url"]["valor"] == "https://es.linkedin.com/company/acme-logistica"
    assert detalle["web"]["fuente_url"] == "https://acmelogistica.test/"
    session.close()


@pytest.mark.integration
def test_id_only_nombre_without_location_is_sin_datos(monkeypatch, clean_database):
    """~3/4 of extracted opportunities only have a fiscal ID as 'name' and no
    location; searching that is pure noise, so it must not cost a provider call."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session, nombre="42973929Q", identificador="42973929Q", localidad=None)
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

    assert result.estado == "sin_datos"
    assert calls == []
    assert sancionado.contacto_estado == "sin_datos"
    attempts = session.execute(select(EnriquecimientoIntento)).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].resultado == "sin_datos"
    session.close()


@pytest.mark.integration
def test_id_like_nombre_with_location_queries_by_identifier(monkeypatch, clean_database):
    session = SyncSessionLocal()
    sancionado = _opportunity(session, nombre="B12345678", identificador="B12345678", localidad="Sevilla")
    session.commit()
    _enable(monkeypatch)

    queries = []

    class RecordingProvider(FixtureProvider):
        def buscar(self, query, max_results):
            queries.append(query)
            return []

    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: RecordingProvider())
    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert queries == ["B12345678 Sevilla"]
    assert result.estado == "no_encontrado"
    session.close()


@pytest.mark.integration
def test_directory_page_social_links_are_not_attributed(monkeypatch, clean_database):
    """A verified company-data directory page (empresite & co.) publishes the
    entity's phone — usable — but its social links point to the DIRECTORY's own
    accounts, and it must never become the entity's website."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    html = """
    <html><body>
    <p>ACME LOGISTICA SL - CIF B12345678</p>
    <p>Teléfono de la empresa: 611222333</p>
    <a href="https://www.linkedin.com/company/eleconomista">Síguenos en LinkedIn</a>
    </body></html>
    """
    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://empresite.eleconomista.es/ACME.html")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: html)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "encontrado"
    assert sancionado.telefono == "611222333"
    assert sancionado.linkedin_url is None
    assert sancionado.web is None
    session.close()


@pytest.mark.integration
def test_non_entity_page_contributes_no_contact_fields(monkeypatch, clean_database):
    """OCU & co. publish their OWN phone/socials on pages merely ABOUT the
    entity (reclamaciones). Even with a CIF match, nothing may be extracted
    from that page's text."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    html = """
    <html><body>
    <p>Reclamaciones sobre ACME LOGISTICA SL - CIF B12345678</p>
    <p>Llámanos al 611222333 o escribe a atencion@ocu.test</p>
    <a href="https://www.linkedin.com/company/ocu-consumidores">LinkedIn</a>
    </body></html>
    """
    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://www.ocu.org/reclamar/empresas/acme")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: html)
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "no_encontrado"
    assert sancionado.telefono is None
    assert sancionado.email is None
    assert sancionado.linkedin_url is None
    assert sancionado.web is None
    session.close()


@pytest.mark.integration
def test_verified_social_profile_candidate_url_is_captured(monkeypatch, clean_database):
    """A social-profile candidate whose snippet carries the full name IS the
    entity's profile — captured even when robots.txt blocks fetching it."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session, nombre="Carlos Gordillo Naranjo", identificador=None)
    session.commit()
    _enable(monkeypatch)

    candidate = SearchCandidate(
        url="https://www.facebook.com/carlos.gordillonaranjo/",
        title="Carlos Gordillo Naranjo",
        snippet="Carlos Gordillo Naranjo is on Facebook. Join Facebook to connect.",
    )
    provider = FixtureProvider({"Carlos Gordillo Naranjo Sevilla": [candidate]})
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: False)

    def _fetch_should_not_be_called(client, url):  # pragma: no cover - only on regression
        raise AssertionError("robots.txt disallowed this URL; it must not be fetched")

    monkeypatch.setattr(enrichment_service, "_fetch", _fetch_should_not_be_called)

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "encontrado"
    assert sancionado.facebook_url == "https://www.facebook.com/carlos.gordillonaranjo"
    assert sancionado.contacto_detalle["facebook_url"]["fuente_url"] == candidate.url
    session.close()


@pytest.mark.integration
def test_reenrichment_corrects_stale_auto_values(monkeypatch, clean_database):
    """A second run replaces what the first one set: corrected values win and
    fields the new run didn't find are cleared — never a stale merge."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    session.commit()
    _enable(monkeypatch)

    html_v1 = """
    <html><body>
    <p>ACME LOGISTICA SL - CIF B12345678</p>
    <p>Contacto: 611222333</p>
    <a href="https://www.linkedin.com/company/cuenta-equivocada">LinkedIn</a>
    </body></html>
    """
    html_v2 = """
    <html><body>
    <p>ACME LOGISTICA SL - CIF B12345678</p>
    <p>Contacto: 699888777</p>
    </body></html>
    """
    pages = {"html": html_v1}

    provider = FixtureProvider({
        "Acme Logistica SL Sevilla": [SearchCandidate(url="https://acmelogistica.test/")],
    })
    monkeypatch.setattr(enrichment_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(enrichment_service, "_robots_allows", lambda url, client: True)
    monkeypatch.setattr(enrichment_service, "_fetch", lambda client, url: pages["html"])
    monkeypatch.setattr(enrichment_service, "_find_legal_links", lambda html, base: [])

    enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()
    assert sancionado.telefono == "611222333"
    assert sancionado.linkedin_url == "https://www.linkedin.com/company/cuenta-equivocada"

    pages["html"] = html_v2
    # Bypass the provider cache so the second run really re-searches.
    session.query(EnriquecimientoCache).delete()
    session.commit()

    result = enrichment_service.enrich_sancionado(session, sancionado)
    session.commit()

    assert result.estado == "encontrado"
    assert sancionado.telefono == "699888777"
    assert sancionado.linkedin_url is None
    assert "linkedin_url" not in (sancionado.contacto_detalle or {})
    session.close()


@pytest.mark.integration
def test_boe_extracted_contact_is_never_overwritten(monkeypatch, clean_database):
    """A telefono/email coming from the BOE extraction itself (present on the
    row, with no enrichment detalle) is official data: enrichment leaves it
    alone even when it finds a different value."""
    session = SyncSessionLocal()
    sancionado = _opportunity(session)
    sancionado.email = "oficial@boe.test"
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
    assert sancionado.email == "oficial@boe.test"
    assert sancionado.telefono == "611222333"
    assert "email" not in (sancionado.contacto_detalle or {})
    session.close()
