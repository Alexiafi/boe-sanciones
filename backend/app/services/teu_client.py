"""Client for the BOE Tablón Edictal Único (TEU) - Suplemento de Notificaciones."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

TEU_INDEX_URL = "https://www.boe.es/boe_n/dias/{year}/{month:02d}/{day:02d}/index.php?l=N"
HTTP_TIMEOUT = 45.0

SANCTION_KEYWORDS = [
    "sancion", "sanciones", "sancionador", "sancionadora", "sancionadores",
    "expediente sancionador", "expedientes sancionadores",
    "resolucion sancionadora",
    "embargo", "embargos", "embargado",
    "diligencia de embargo",
    "apremio", "providencia de apremio", "via de apremio",
    "procedimiento de apremio",
    "deuda", "deudas", "deudor", "deudores",
    "deuda tributaria", "deudas tributarias",
    "multa", "multas",
    "infraccion", "infracciones",
    "acta de infraccion", "actas de infraccion",
    "requerimiento de pago",
    "liquidacion", "liquidaciones",
    "impago", "moroso", "morosos",
    "penalidad", "penalidades",
    "ejecucion forzosa", "ejecucion subsidiaria",
    "recaudacion ejecutiva",
    "titulo ejecutivo",
    "baja cautelar",
    "propuesta de resolucion",
    "reclamacion de deuda",
]

MAX_TEU_PER_RUN = 200

EXCLUDE_KEYWORDS = [
    "expropiacion forzosa",
    "renta garantizada",
    "discapacidad",
    "prestacion por desempleo",
    "subvencion",
    "concesion de aguas",
    "estadistica",
    "encuesta",
    "informacion publica",
    "plan urbanistico",
    "plan parcial",
    "plan general",
    "acta de requerimiento",
    "notaria de ",
    "notaria ",
    "registro de la propiedad",
]

_ENTRY_RE = re.compile(
    r'<li\s+class="notif">\s*<p>(.*?)</p>'
    r'.*?href="([^"]*?/not\.php\?id=(BOE-N-\d+-\d+))"',
    re.S,
)

_DEPT_H5_RE = re.compile(r'<h5[^>]*>(.*?)</h5>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    return _strip_accents(text.lower())


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
def fetch_teu_index(fecha: date) -> str:
    url = TEU_INDEX_URL.format(year=fecha.year, month=fecha.month, day=fecha.day)
    logger.info("Fetching TEU index for %s: %s", fecha, url)
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def parse_teu_index(html: str, fecha: date) -> list[dict[str, Any]]:
    """Parse the TEU HTML index extracting full title, department, and BOE-N id."""
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    dept_positions: list[tuple[int, str]] = []
    for m in _DEPT_H5_RE.finditer(html):
        dept_text = _TAG_RE.sub("", m.group(1)).strip()
        dept_positions.append((m.start(), dept_text))

    def _find_dept(pos: int) -> str:
        dept = ""
        for dp, dt in dept_positions:
            if dp < pos:
                dept = dt
            else:
                break
        return dept

    for m in _ENTRY_RE.finditer(html):
        raw_title = _TAG_RE.sub("", m.group(1)).strip()
        url_path = m.group(2)
        boe_id = m.group(3)

        if boe_id in seen_ids:
            continue
        seen_ids.add(boe_id)

        dept = _find_dept(m.start())

        entries.append({
            "identificador": boe_id,
            "titulo": raw_title,
            "departamento_nombre": dept,
            "fecha_publicacion": fecha,
            "seccion_codigo": "TEU",
            "seccion_nombre": "Tablón Edictal Único - Suplemento de Notificaciones",
            "url_pdf": url_path,
            "source": "teu",
        })

    logger.info("Parsed %d TEU entries for %s", len(entries), fecha)
    return entries


def filter_relevant_teu_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter TEU entries keeping only sanction/embargo/debt-related notifications."""
    relevant = []
    for entry in entries:
        search_text = _normalize(entry["titulo"] + " " + entry.get("departamento_nombre", ""))

        if any(kw in search_text for kw in EXCLUDE_KEYWORDS):
            continue

        if any(kw in search_text for kw in SANCTION_KEYWORDS):
            relevant.append(entry)

    logger.info(
        "Filtered %d relevant TEU entries from %d total",
        len(relevant), len(entries),
    )
    return relevant


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=15))
def fetch_teu_pdf(url: str) -> bytes:
    if not url:
        return b""
    full_url = url if url.startswith("http") else f"{settings.boe_base_url}{url}"
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = client.get(full_url)
        resp.raise_for_status()
        return resp.content
