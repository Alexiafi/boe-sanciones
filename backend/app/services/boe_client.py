"""Client for the official BOE open-data API."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def fetch_sumario(fecha: date) -> dict[str, Any]:
    yyyymmdd = fecha.strftime("%Y%m%d")
    url = SUMARIO_URL.format(yyyymmdd=yyyymmdd)
    logger.info("Fetching BOE summary for %s: %s", yyyymmdd, url)

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url, headers={"Accept": "application/json"})
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
