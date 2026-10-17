"""Unit tests for evidence matching. No database, no network."""

from __future__ import annotations

from app.services.enrichment.verify import verify


def test_razon_social_with_commas_matches_website_without_sa():
    page = (
        "Gesconsult SGIIC C/Serrano 37 Tel: +34 91 577 49 31 "
        "Email: fondos@gesconsult.es"
    )
    outcome = verify(page_text=page, identificador=None, nombre="Gesconsult, SA, SGIIC")
    assert outcome.confidence == 0.6
    assert outcome.evidencia and "Gesconsult" in outcome.evidencia


def test_dotted_legal_form_matches_compact_razon_social():
    page = "Gesconsult S.A. S.G.I.I.C. Copyright 2020"
    outcome = verify(page_text=page, identificador=None, nombre="Gesconsult, SA, SGIIC")
    assert outcome.confidence == 0.6


def test_unrelated_company_is_not_evidence():
    page = "Otra gestora distinta SL Tel: 611 222 333"
    outcome = verify(page_text=page, identificador=None, nombre="Gesconsult, SA, SGIIC")
    assert outcome.confidence == 0.0
    assert outcome.evidencia is None


def test_identifier_match_outranks_name():
    page = "Texto cualquiera CIF B12345678"
    outcome = verify(page_text=page, identificador="B12345678", nombre="Acme")
    assert outcome.confidence == 0.9
    assert "B12345678" in (outcome.evidencia or "")
