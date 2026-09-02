"""Extract plain text from BOE document XML, HTML, or PDF."""

from __future__ import annotations

import io
import logging

from bs4 import BeautifulSoup
from lxml import etree

logger = logging.getLogger(__name__)


def xml_to_text(xml_content: str) -> str:
    """Extract text from a BOE document XML, focusing on <texto> elements."""
    try:
        root = etree.fromstring(xml_content.encode("utf-8", errors="ignore"))

        texto_nodes = root.xpath("//texto")
        if texto_nodes:
            parts = []
            for node in texto_nodes:
                parts.append(_etree_text(node))
            return " ".join(parts)

        return _etree_text(root)
    except Exception:
        logger.warning("Failed to parse XML with lxml, falling back to BeautifulSoup")
        return _bs_xml_to_text(xml_content)


def _etree_text(node) -> str:
    """Recursively gather text from an lxml element tree."""
    texts = node.itertext()
    return " ".join(t.strip() for t in texts if t.strip())


def _bs_xml_to_text(xml_content: str) -> str:
    soup = BeautifulSoup(xml_content, "xml")
    texto = soup.find("texto")
    if texto:
        return " ".join(texto.get_text(" ", strip=True).split())
    return " ".join(soup.get_text(" ", strip=True).split())


def html_to_text(html_content: str) -> str:
    """Extract text from a BOE document HTML page."""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()

    selectors = [
        "div.documento-texto",
        "div#textoxslt",
        "div#texto",
        "article",
        "div#contenido",
        "main",
        "div.content",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return " ".join(el.get_text(" ", strip=True).split())

    return " ".join(soup.get_text(" ", strip=True).split())


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF using pdfminer."""
    try:
        from pdfminer.high_level import extract_text
        with io.BytesIO(pdf_bytes) as f:
            text = extract_text(f)
        return " ".join(text.split())
    except Exception:
        logger.exception("Failed to extract text from PDF")
        return ""


# (content_type, bytes, url_origen) of the document actually downloaded, so
# callers can archive the original bytes (see services/archivo.py).
RawDocument = tuple[str, bytes, str]


def extract_text_from_document(
    url_xml: str | None,
    url_html: str | None,
    url_pdf: str | None,
    fetch_fn,
    fetch_pdf_fn,
) -> tuple[str, str, RawDocument | None]:
    """
    Try XML first, then HTML, then PDF. Returns (text, source, raw).
    fetch_fn(url) -> str, fetch_pdf_fn(url) -> bytes
    """
    if url_xml:
        try:
            raw = fetch_fn(url_xml)
            text = xml_to_text(raw)
            if text.strip():
                return text, "xml", ("text/xml", raw.encode("utf-8", errors="ignore"), url_xml)
        except Exception:
            logger.warning("Failed to fetch/parse XML: %s", url_xml)

    if url_html:
        try:
            raw = fetch_fn(url_html)
            text = html_to_text(raw)
            if text.strip():
                return text, "html", ("text/html", raw.encode("utf-8", errors="ignore"), url_html)
        except Exception:
            logger.warning("Failed to fetch/parse HTML: %s", url_html)

    if url_pdf:
        try:
            raw_bytes = fetch_pdf_fn(url_pdf)
            text = pdf_to_text(raw_bytes)
            if text.strip():
                return text, "pdf", ("application/pdf", raw_bytes, url_pdf)
        except Exception:
            logger.warning("Failed to fetch/parse PDF: %s", url_pdf)

    return "", "none", None
