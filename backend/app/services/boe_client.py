"""Client for the official BOE open-data API."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

SUMARIO_URL = f"{settings.boe_api_base_url}/sumario/{{yyyymmdd}}"
HTTP_TIMEOUT = 30.0


def _ensure_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def absoluta_url_boe(url: str | None) -> str | None:
    """Turn a BOE relative path into an absolute URL.

    The open-data API and the TEU HTML index often store paths such as
    ``/boe_n/dias/2026/09/02/not.php?id=…``. Using those as ``<a href>``
    makes the browser resolve them against this app (localhost) and 404.
    """
    if not url:
        return None
    value = url.strip()
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    base = settings.boe_base_url.rstrip("/")
    path = value if value.startswith("/") else f"/{value}"
    return f"{base}{path}"


def url_documento_boe(*, boe_id: str, fecha_publicacion: date, url_html: str | None, url_pdf: str | None) -> str:
    """Best public URL for a document: its HTML, else its PDF, else the
    canonical BOE/TEU viewer built from the identifier."""
    if url_html:
        return absoluta_url_boe(url_html) or ""
    if url_pdf:
        return absoluta_url_boe(url_pdf) or ""
    base = settings.boe_base_url.rstrip("/")
    if boe_id.startswith("BOE-N-"):
        return (
            f"{base}/boe_n/dias/{fecha_publicacion.year}/{fecha_publicacion.month:02d}/"
            f"{fecha_publicacion.day:02d}/not.php?id={boe_id}"
        )
    return f"{base}/diario_boe/txt.php?id={boe_id}"


class BoeSumarioNoDisponible(Exception):
    """The BOE has no summary for that date (HTTP 404): either it is not
    published yet (the daily edition appears around 07:30–08:30 Madrid) or
    there is no edition that day (Sundays, some holidays). Not retried —
    hammering the API does not make the edition appear sooner; the beat
    schedule simply tries again later."""

    def __init__(self, fecha: date) -> None:
        self.fecha = fecha
        super().__init__(
            f"El BOE no tiene sumario publicado para {fecha.isoformat()} (404): "
            "todavía no está disponible o no hay edición ese día."
        )


@retry(
    stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30),
    retry=retry_if_not_exception_type(BoeSumarioNoDisponible), reraise=True,
)
def fetch_sumario(fecha: date) -> dict[str, Any]:
    yyyymmdd = fecha.strftime("%Y%m%d")
    url = SUMARIO_URL.format(yyyymmdd=yyyymmdd)
    logger.info("Fetching BOE summary for %s: %s", yyyymmdd, url)

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers={"Accept": "application/json"})
        if resp.status_code == 404:
            raise BoeSumarioNoDisponible(fecha)
        resp.raise_for_status()
        return resp.json()


def flatten_sumario(payload: dict[str, Any], fecha: date) -> list[dict[str, Any]]:
    """Flatten the nested BOE summary JSON into a flat list of document items."""
    docs: list[dict[str, Any]] = []
    sumario = payload["data"]["sumario"]

    for diario in _ensure_list(sumario.get("diario")):
        diario_numero = diario.get("numero")
        for seccion in _ensure_list(diario.get("seccion")):
            sec_codigo = seccion.get("codigo")
            sec_nombre = seccion.get("nombre")
            for depto in _ensure_list(seccion.get("departamento")):
                dep_codigo = depto.get("codigo")
                dep_nombre = depto.get("nombre")
                for epigrafe in _ensure_list(depto.get("epigrafe")):
                    epi_nombre = epigrafe.get("nombre")
                    for item in _ensure_list(epigrafe.get("item")):
                        url_pdf_obj = item.get("url_pdf", {})
                        url_pdf = url_pdf_obj.get("texto", "") if isinstance(url_pdf_obj, dict) else (url_pdf_obj or "")

                        docs.append({
                            "fecha_publicacion": fecha,
                            "diario_numero": int(diario_numero) if diario_numero else None,
                            "seccion_codigo": sec_codigo,
                            "seccion_nombre": sec_nombre,
                            "departamento_codigo": dep_codigo,
                            "departamento_nombre": dep_nombre,
                            "epigrafe_nombre": epi_nombre,
                            "identificador": item.get("identificador"),
                            "titulo": item.get("titulo", ""),
                            "url_html": item.get("url_html", ""),
                            "url_xml": item.get("url_xml", ""),
                            "url_pdf": url_pdf,
                            "raw_item": item,
                        })

    logger.info("Flattened %d documents from BOE summary", len(docs))
    return docs


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=15))
def fetch_document_content(url: str) -> str:
    """Fetch the raw XML or HTML content of a BOE document."""
    if not url:
        return ""
    full_url = url if url.startswith("http") else f"{settings.boe_base_url}{url}"
    logger.debug("Fetching document: %s", full_url)

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(full_url)
        resp.raise_for_status()
        return resp.text


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10))
def fetch_document_pdf(url: str) -> bytes:
    if not url:
        return b""
    full_url = url if url.startswith("http") else f"{settings.boe_base_url}{url}"
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(full_url)
        resp.raise_for_status()
        return resp.content


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
