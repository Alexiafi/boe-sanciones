"""Pure extraction/normalisation tests for the enrichment cascade: no database,
no network. These run unconditionally (no TEST_DATABASE_URL_SYNC needed), like
test_historico_patterns.py."""

from __future__ import annotations

import httpx

from app.services.enrichment import patterns
from app.services.enrichment.service import _fetch, _normalise_candidate_url, _trim_page


def test_find_phones_prefers_prefixed_or_separated_numbers():
    text = "<p>data-id 837640448</p><p>Tel: +34 932 20 38 58</p><p>Otro: 936836613</p>"
    phones = patterns.find_phones(text)
    assert phones == ["+34 932 20 38 58"]


def test_find_phones_requires_spanish_shape_and_phone_context():
    assert patterns.find_phones("SKU 611222333 en el JSON") == []
    assert patterns.find_phones("Contacto: 611222333") == ["611222333"]
    assert patterns.find_phones('<a href="tel:+34932203858">llamar</a>') == ["+34932203858"]
    assert patterns.find_phones("Teléfono 900 123 123") == ["900 123 123"]
    assert patterns.find_phones("Tel: 7-2149-4331 y 88-17.5 8.51 0") == []
    assert patterns.find_phones("Tel: 803123123") == []  # tarificación adicional, no contacto útil
    assert patterns.national_digits("+34 612 345 678") == "612345678"
    assert patterns.is_valid_spanish_national("912345678") is True
    assert patterns.is_valid_spanish_national("512345678") is False
    assert patterns.is_valid_spanish_national("12345") is False


def test_find_emails_drops_asset_filenames_and_placeholders():
    text = "logo@2x.png info@northdeco.com email@example.com icon@1x.svg"
    assert patterns.find_emails(text) == ["info@northdeco.com"]


def test_extract_razon_social_from_einforma_title():
    title = "CONSTRUHOGAR GRACIDA SIGLO XXI SL - Informe de empresa | einforma"
    assert patterns.extract_razon_social(title) == "CONSTRUHOGAR GRACIDA SIGLO XXI SL"
    slug_url = "https://www.einforma.com/informacion-empresa/construhogar-gracida-siglo-xxi"
    assert patterns.razon_from_directory_slug(slug_url) == "CONSTRUHOGAR GRACIDA SIGLO XXI"


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
    assert patterns.is_generic_directory("www.finect.com")
    assert not patterns.is_generic_directory("northdeco.com")
    assert patterns.is_non_entity_site("www.finect.com")
    assert patterns.is_non_entity_site("es.investing.com")
    assert patterns.is_non_entity_site("www.cnmv.es")
    assert not patterns.is_non_entity_site("gesconsult.com")


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


def test_fetch_retries_forbidden_with_fallback_user_agent():
    class _Resp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text
            self.request = httpx.Request("GET", "https://gesconsult.test/")

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "Client error",
                    request=self.request,
                    response=self,
                )

    class _Client:
        def __init__(self):
            self.uas: list[str] = []

        def get(self, url, headers=None, timeout=None, follow_redirects=None):
            ua = (headers or {}).get("User-Agent")
            self.uas.append(ua)
            if ua == "Mozilla/5.0":
                return _Resp(403, "forbidden")
            return _Resp(200, "<html>ok</html>")

    client = _Client()
    assert _fetch(client, "https://gesconsult.test/") == "<html>ok</html>"
    assert client.uas == ["Mozilla/5.0", "python-httpx/0.28.1"]


def test_trim_page_keeps_footer_contact_on_huge_html():
    footer = "Tel: +34 91 577 49 31 Email: fondos@gesconsult.es"
    html = "<nav>Contacto</nav>" + ("x" * 900_000) + footer
    trimmed = _trim_page(html)
    assert "Contacto" in trimmed
    assert "fondos@gesconsult.es" in trimmed
    assert "+34 91 577 49 31" in trimmed
    assert len(trimmed) <= 300_000




def test_public_bodies_and_official_gazettes_are_not_a_source_of_contact():
    """A gazette page that lists a DNI is the notice itself: its phone/email is
    the office's. Only the BOE was excluded before."""
    from app.services.enrichment.patterns import is_non_entity_site

    for dominio in ("www.boe.es", "sede.dgt.gob.es", "ajuntament.example.cat", "bop.diba.cat", "www.ayuntamientodeleon.test",
                    "tablonedictal.example.es", "sede.agenciatributaria.gob.es", "www.dipucadiz.es", "boletin.example.es"):
        assert is_non_entity_site(dominio), dominio
    # Fragments only count at the start of a domain label: these are companies.
    for dominio in ("www.acmelogistica.es", "transportes-sur.com", "www.einforma.com", "hayton.com", "playtown.es", "desbop.com"):
        assert not is_non_entity_site(dominio), dominio


# --- attribution (real names and texts from the client's cases, 2026-10-17) ---

def test_full_name_does_not_match_a_longer_name_or_another_legal_form():
    assert not patterns.menciona_nombre("Kubika Grupo Inmobiliario Sociedad Limitada, Valencia", "KUBIKA S L")
    assert patterns.menciona_nombre("KUBIKA SL: Teléfono, CIF y Dirección", "KUBIKA S L")
    assert not patterns.menciona_nombre("© 2026 Ágora Patrimonial S.A.S. Bogotá", "Ágora Patrimonial S.L.")
    assert patterns.menciona_nombre("AGORA PATRIMONIAL SL | Datos de Empresa", "Ágora Patrimonial S.L.")
    assert patterns.menciona_nombre(
        "ACCESORIOS DORADOS SOCIEDAD LIMITADA | El último teléfono ...", "ACCESORIOS DORADOS SL",
    )
    assert not patterns.menciona_nombre("Accesorios Moda Y Novedades Sl - Teléfono", "ACCESORIOS DORADOS SL")
    assert patterns.menciona_nombre_con_forma("Responsable: GRUPO BOHEME SENSATIONS, S. L. Domicilio", "GRUPO BOHEME SENSATIONS SL")


def test_contact_next_to_the_cif_but_not_the_directory_frame_or_sidebar():
    html = (
        "<html><body>"
        '<header><a href="tel:900213215">900 213 215</a></header>'
        "<main><h1>GRUPO BOHEME SENSATIONS SL</h1><p>CIF: B98854250</p><p>Teléfono: 620 94 07 19</p></main>"
        "<aside><p>GEST BARFISA SL con NIF B60355518. Teléfono: 935894337</p></aside>"
        "<footer>Atención al cliente 900 213 215 · atencionclientes@iberinform.es</footer>"
        "</body></html>"
    )
    visible = patterns.texto_visible(html, sin_marco=True)
    telefonos, emails = patterns.contacto_cercano(visible, "B98854250", "GRUPO BOHEME SENSATIONS SL")
    assert telefonos == ["620 94 07 19"]
    assert emails == []


def test_other_party_identifier_bounds_the_contact():
    texto = "70. PERIS LOGÍSTICA, S.L.. C.I.F. B-97491344. Tel. Móvil 650 977 675. 71. OTRA SL C.I.F. B-11111111. Tel. 611 222 333."
    telefonos, _ = patterns.contacto_cercano(texto, "B97491344", "PERIS LOGISTICA SL")
    assert telefonos == ["650 977 675"]


def test_official_notice_or_list_page_is_detected():
    notificacion = (
        "AYUNTAMIENTO DE SANT CUGAT. Notificación de la resolución del expediente sancionador. "
        "En virtud de lo dispuesto en la Ley 39/2015 se notifica a 2010 SERIGRAFIA SL B65350845. Tel. 935 650 000"
    )
    assert patterns.parece_pagina_oficial(notificacion, "B65350845")
    lista = "B98854250 GRUPO BOHEME SENSATIONS S.L. 12. B98930910 TYRVAL IMPORT EXPORT S.L. B11111111 X SL B22222222 Y SL"
    assert patterns.parece_pagina_oficial(lista, "B98854250")
    assert not patterns.parece_pagina_oficial("Moldes Diaz SA. CIF A58017732. Teléfono 936853050", "A58017732")


def test_name_from_directory_titles():
    assert patterns.razon_de_titulo("GRUPO BOHEME SENSATIONS SL - NIF B98854250 - Infonif") == "GRUPO BOHEME SENSATIONS SL"
    assert patterns.razon_de_titulo("Accesorios Dorados Sociedad Limitada, Girona") == "Accesorios Dorados SL"
    assert patterns.razon_de_titulo("Moldes Diaz SA: consulte teléfono, CIF y dirección") == "Moldes Diaz SA"
    assert patterns.limpiar_razon("B55257109 ACCESORIOS DORADOS SLU") == "ACCESORIOS DORADOS SLU"


def test_social_profile_must_look_like_the_company():
    assert patterns.perfil_parecido("https://www.instagram.com/bohemesensations", "GRUPO BOHEME SENSATIONS SL", None)
    assert not patterns.perfil_parecido("https://www.facebook.com/artbees", "ITEAF 7 ISLAS SL", "iteaf7islas.es")
