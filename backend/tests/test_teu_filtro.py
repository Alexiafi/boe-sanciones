"""TEU relevance filter and index fetching (no network: an httpx mock transport)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.services import teu_client
from app.services.teu_client import filter_relevant_teu_entries, fetch_teu_index


def _entrada(titulo: str, dept: str = "BARCELONA") -> dict:
    return {"identificador": f"BOE-N-2026-{abs(hash(titulo)) % 10**6}", "titulo": titulo, "departamento_nombre": dept}


@pytest.mark.parametrize("titulo,dept", [
    # Municipal / regional traffic notices never say "sanción": they were all missed.
    ("Anuncio de notificación de 25 de septiembre de 2026 en procedimiento Circulación e incidencias en la vía pública (Exp. 4679/2026).", "BARCELONA"),
    ("DIRECCIÓN DE MOVILIDAD. Anuncio de notificación de 21 de septiembre de 2026 en procedimiento de Notificaciones de denuncia.", "BIZKAIA"),
    ("Anuncio de notificación de 24 de septiembre de 2026 en procedimiento Notificación de denuncia.", "ILLES BALEARS"),
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ALMERÍA. Anuncio de notificación de 28 de septiembre de 2026 en procedimiento de pérdida de vigencia de la autorización administrativa para conducir.", "MINISTERIO DEL INTERIOR"),
    ("Anuncio de notificación de 21 de septiembre de 2026 en procedimiento de requerimiento de retirada del vehículo con matrícula 2566 FLS.", "A CORUÑA"),
    # The classics still work.
    ("Anuncio de notificación de 21 de septiembre de 2026 en procedimientos sancionadores.", "COMUNIDAD AUTÓNOMA DE CATALUÑA"),
    ("TESORERIA GENERAL DE LA SEGURIDAD SOCIAL. Anuncio de notificación de providencia de apremio.", "MINISTERIO DE INCLUSIÓN"),
])
def test_traffic_and_sanction_notices_are_relevant(titulo, dept):
    assert len(filter_relevant_teu_entries([_entrada(titulo, dept)])) == 1


@pytest.mark.parametrize("titulo,dept", [
    # Exam results are traffic notices but not fines or debts.
    ("JEFATURA PROVINCIAL DE TRÁFICO DE ÁLAVA. Anuncio de notificación en procedimiento de obtención del permiso de conducción de la clase C (Calificación de prueba).", "MINISTERIO DEL INTERIOR"),
    ("Anuncio de notificación de 24 de septiembre de 2026 en procedimiento Baja de oficio del Padrón Municipal de Habitantes.", "BARCELONA"),
    ("Anuncio de notificación en procedimiento de baja forzosa gestionados por el Col·legi", "REGISTROS DE LA PROPIEDAD, MERCANTILES"),
    ("Anuncio de notificación de subvención para vehículos eléctricos.", "MADRID"),
])
def test_unrelated_notices_stay_out(titulo, dept):
    assert filter_relevant_teu_entries([_entrada(titulo, dept)]) == []


_CLIENTE_REAL = httpx.Client   # captured before any test patches ``httpx.Client``


def _cliente_http(handler):
    return _CLIENTE_REAL(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture
def parchear_cliente(monkeypatch):
    def _instalar(handler):
        monkeypatch.setattr(teu_client.httpx, "Client", lambda **kwargs: _cliente_http(handler))
    return _instalar


def test_a_date_without_supplement_is_empty_not_an_error(parchear_cliente):
    """Sunday: 404. Used to be retried three times and counted as a failure."""
    llamadas = []

    def handler(request):
        llamadas.append(request.url.path)
        return httpx.Response(404, text="no")

    parchear_cliente(handler)
    assert fetch_teu_index(date(2026, 9, 27)) == ""
    assert len(llamadas) == 1  # not retried


def test_a_redirect_to_the_ordinary_summary_is_not_a_teu_index(parchear_cliente):
    """2026-09-30: the BOE redirected the TEU URL to the ordinary summary page."""
    def handler(request):
        if request.url.path.startswith("/boe_n/"):
            return httpx.Response(302, headers={"location": "/boe/dias/2026/09/30/index.php?d=242"})
        return httpx.Response(200, text="<html>Sumario ordinario</html>")

    parchear_cliente(handler)
    assert fetch_teu_index(date(2026, 9, 30)) == ""


def test_a_real_index_is_returned(parchear_cliente):
    parchear_cliente(lambda request: httpx.Response(200, text='<li class="notif">…</li>'))
    assert "notif" in fetch_teu_index(date(2026, 9, 29))
