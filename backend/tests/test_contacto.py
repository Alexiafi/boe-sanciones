"""The Administration's own contact data must never become a sanctioned party's."""

from __future__ import annotations

import pytest

from app.services.contacto import es_email_institucional, es_telefono_institucional


@pytest.mark.parametrize("valor", ["012", "060", "091", "900 100 200", "901 16 65 65", "902123456", "+34 902 123 456"])
def test_institutional_phone_numbers(valor):
    assert es_telefono_institucional(valor)


@pytest.mark.parametrize("valor", ["611222333", "+34 611 222 333", "934 567 890", "955123456", None, ""])
def test_private_phone_numbers_are_kept(valor):
    assert not es_telefono_institucional(valor)


@pytest.mark.parametrize("valor", [
    "recaudacion@dipucadiz.es", "atencion@dgt.es", "info@bcn.cat", "tributos@ayuntamientodeleon.test",
    "x@aytomadrid.test", "contacto@juntadeandalucia.es", "multas@sede.gob.es", "a@gencat.cat",
])
def test_institutional_emails(valor):
    assert es_email_institucional(valor)


@pytest.mark.parametrize("valor", ["info@acmelogistica.test", "juan@gmail.com", "admin@transportes-sur.es", None, "sin-arroba"])
def test_private_emails_are_kept(valor):
    assert not es_email_institucional(valor)


@pytest.mark.integration
def test_the_extraction_never_persists_a_phone_or_email_from_the_notice():
    """On a real database all 1,481 extracted phones were the issuing office's."""
    from app.services.extractor import AfectadoExtraido
    from app.services.oportunidades import extracted_values

    valores = extracted_values(AfectadoExtraido(
        identificador="B12345678", nombre="Acme SL", localidad="Reinosa", telefono="942 751 245", email="multas@arona.org",
    ))
    assert "telefono" not in valores and "email" not in valores
    assert valores["identificador"] == "B12345678" and valores["localidad"] == "Reinosa"
