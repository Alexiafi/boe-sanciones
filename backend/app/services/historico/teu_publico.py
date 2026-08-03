"""Optional connector for the TEU's own public search-by-NIF form.

Off by default and never called from any automatic path (no Celery beat
entry, no default-on flag, ``incluir_teu`` defaults to ``False`` at every
layer). Modelled on ``app/services/enrichment/providers/``: a ``Protocol``
plus a registry, so real network access is confined to one adapter
(``TeuBuscadorHttp``) that is never imported or constructed unless a caller
explicitly opts in through ``get_teu_buscador``.

Why this matters for the R-1 limitation documented in PLAN.md: the TEU only
allows free public consultation for ~90 days after publication. This
connector, even when enabled, can only ever surface what is still inside that
window at query time — it does not and cannot recover older TEU history. The
only thing that recovers older TEU history is this system's own daily
accumulation (see ``app/tasks/scraping.py``), which is why ``AVISO_TEU``
below is surfaced everywhere a history search response is returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from app.config import settings

TEU_VENTANA_PUBLICA_DIAS = 90
AVISO_TEU = (
    "El Tablón Edictal Único (TEU) solo permite consulta pública durante 90 días desde la "
    "publicación. Para fechas anteriores solo se muestra lo que este sistema haya acumulado "
    "por sí mismo desde su puesta en marcha; el BOE ordinario sí cubre el histórico completo."
)


class TeuSearchDisabled(ValueError):
    """Raised when a TEU public search is attempted while disabled."""


@dataclass(frozen=True)
class EntradaTeu:
    identificador: str
    titulo: str
    fecha_publicacion: date
    departamento_nombre: str | None = None
    url_pdf: str | None = None


class TeuBuscador(Protocol):
    nombre: str

    def buscar_por_clave(self, clave: str, *, desde: date, hasta: date) -> list[EntradaTeu]: ...


class TeuBuscadorFixture:
    """No network. The only adapter exercised in tests and local dev."""

    nombre = "fixture"

    def __init__(self, fixtures: dict[str, list[EntradaTeu]] | None = None):
        self._fixtures = fixtures or {}

    def buscar_por_clave(self, clave: str, *, desde: date, hasta: date) -> list[EntradaTeu]:
        return [
            entrada
            for entrada in self._fixtures.get(clave, [])
            if desde <= entrada.fecha_publicacion <= hasta
        ]


class TeuBuscadorHttp:
    """Real scraping of the public TEU search form.

    ``httpx.Client`` is constructed only inside ``buscar_por_clave``, never at
    import or ``__init__`` time — so a test can prove this adapter never
    touches the network simply by not calling that method (or, in the test
    suite's autouse guard, by booby-trapping ``httpx.Client`` itself).
    """

    nombre = "http"
    _SEARCH_URL = "https://sede.boe.gob.es/notificaciones/pdf/buscar.php"
    _HTTP_TIMEOUT = 45.0

    def buscar_por_clave(self, clave: str, *, desde: date, hasta: date) -> list[EntradaTeu]:
        import httpx
        from tenacity import retry, stop_after_attempt, wait_exponential

        from app.services.teu_client import _TAG_RE, _normalize  # reuse existing HTML helpers

        @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=15))
        def _fetch() -> str:
            with httpx.Client(timeout=self._HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(self._SEARCH_URL, params={"campo": clave})
                resp.raise_for_status()
                return resp.text

        html = _fetch()
        # Minimal, defensive parse: the public form's markup is not a stable
        # contract, so this only extracts what it can safely recognise and
        # never raises on unexpected shapes — an empty result is preferred
        # over a crash on a page redesign.
        entradas: list[EntradaTeu] = []
        for chunk in html.split("<tr")[1:][: settings.teu_public_search_max_por_consulta]:
            texto = _TAG_RE.sub(" ", chunk)
            texto = _normalize(texto)
            if not texto.strip():
                continue
            entradas.append(
                EntradaTeu(identificador="", titulo=texto.strip()[:500], fecha_publicacion=desde)
            )
        return entradas


_REGISTRY: dict[str, type] = {"fixture": TeuBuscadorFixture, "http": TeuBuscadorHttp}


def get_teu_buscador(nombre: str | None = None) -> TeuBuscador | None:
    name = nombre or settings.teu_public_search_provider
    buscador_cls = _REGISTRY.get(name)
    if buscador_cls is None:
        return None
    return buscador_cls()


def teu_search_available(nombre: str | None = None) -> tuple[bool, str | None]:
    if not settings.teu_public_search_enabled:
        return False, "La búsqueda pública del TEU está desactivada (TEU_PUBLIC_SEARCH_ENABLED=false)."
    name = nombre or settings.teu_public_search_provider
    if name == "none":
        return False, "No hay conector TEU configurado (TEU_PUBLIC_SEARCH_PROVIDER=none)."
    if get_teu_buscador(name) is None:
        return False, f"Conector TEU desconocido: '{name}'."
    return True, None


def ventana_publica_desde(hoy: date | None = None) -> date:
    hoy = hoy or date.today()
    return hoy - timedelta(days=TEU_VENTANA_PUBLICA_DIAS)


def fuera_de_ventana_teu(fecha_publicacion: date, *, hoy: date | None = None) -> bool:
    return fecha_publicacion < ventana_publica_desde(hoy)
