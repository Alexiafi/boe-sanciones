"""Pure extraction/normalisation tests for the enrichment cascade: no database,
no network. These run unconditionally (no TEST_DATABASE_URL_SYNC needed), like
test_historico_patterns.py."""

from __future__ import annotations

from app.services.enrichment import patterns
from app.services.enrichment.service import _normalise_candidate_url


def test_find_phones_prefers_prefixed_or_separated_numbers():
    text = "<p>data-id 837640448</p><p>Tel: +34 932 20 38 58</p><p>Otro: 936836613</p>"
    phones = patterns.find_phones(text)
    assert phones[0] == "+34 932 20 38 58"
    assert set(phones) == {"+34 932 20 38 58", "837640448", "936836613"}


def test_find_emails_drops_asset_filenames_and_placeholders():
    text = "logo@2x.png info@northdeco.com email@example.com icon@1x.svg"
    assert patterns.find_emails(text) == ["info@northdeco.com"]


def test_find_social_extracts_profiles_and_skips_share_endpoints():
    text = (
        '<a href="https://es.linkedin.com/company/joskortex">LinkedIn</a>'
        '<a href="https://www.linkedin.com/shareArticle?url=x">compartir</a>'
        '<a href="https://www.facebook.com/joskortex.sl">FB</a>'
        '<a href="https://www.facebook.com/sharer/sharer.php?u=x">compartir</a>'
        '<a href="https://www.instagram.com/northdeco/">IG</a>'
        '<a href="https://x.com/northdeco">X</a>'
    )
    social = patterns.find_social(text)
    assert social["linkedin_url"] == ["https://es.linkedin.com/company/joskortex"]
    assert social["facebook_url"] == ["https://www.facebook.com/joskortex.sl"]
    assert social["instagram_url"] == ["https://www.instagram.com/northdeco"]
    assert social["twitter_url"] == ["https://x.com/northdeco"]


def test_is_generic_directory_matches_subdomains():
    assert patterns.is_generic_directory("empresite.eleconomista.es")
    assert patterns.is_generic_directory("www.dnb.com")
    assert patterns.is_generic_directory("www.boe.es")
    assert not patterns.is_generic_directory("northdeco.com")


def test_normalise_candidate_url_strips_tracking_and_english_locale():
    assert (
        _normalise_candidate_url("https://northdeco.com/en-dk/pages/aviso-legal?srsltid=ABC&utm_source=x")
        == "https://northdeco.com/pages/aviso-legal"
    )
    assert (
        _normalise_candidate_url("https://www.infoempresa.com/en-in/en/company/joskortex-sl")
        == "https://www.infoempresa.com/company/joskortex-sl"
    )
    # Non-tracking params and Spanish paths are preserved.
    assert (
        _normalise_candidate_url("https://acme.test/contacto?page=2")
        == "https://acme.test/contacto?page=2"
    )
