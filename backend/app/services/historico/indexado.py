"""Idempotent upsert of ``HistoricoDoc`` rows.

Shared by three callers, all free (no LLM, no paid API):
- ``app/tasks/historico_backfill.py`` (manual, gated backfill)
- ``app/tasks/scraping.py`` (daily accumulation — reuses text already in
  memory from the operational pipeline, at zero marginal network/API cost)
- ``app/services/historico/teu_publico.py`` (optional TEU public-search
  results, materialised as ``HistoricoDoc(fuente="teu")`` so the rest of the
  system treats them uniformly)
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.historico import HistoricoDoc
from app.services.boe_client import hash_text
from app.services.historico.patterns import ClavesExtraidas, extraer_claves

EXTRACTO_MAX_CHARS = 4_000


def _merge_listas(existente: list | None, nueva: list) -> list:
    combinado = list(dict.fromkeys((existente or []) + nueva))
    return combinado


def upsert_historico_doc(
    db: Session,
    *,
    boe_id: str,
    fuente: str,
    fecha_publicacion: date,
    titulo: str,
    origen_indexado: str,
    seccion_codigo: str | None = None,
    departamento_nombre: str | None = None,
    url_html: str | None = None,
    url_xml: str | None = None,
    url_pdf: str | None = None,
    texto: str | None = None,
    familia_sancionadora: str | None = None,
    confidence: float | None = None,
    guardar_texto: bool = False,
    claves: ClavesExtraidas | None = None,
) -> tuple[HistoricoDoc, bool]:
    """Insert or merge one document into the historical index.

    Idempotent on ``boe_id``: re-indexing the same document (a backfill day
    re-processed after an interruption, or the daily pipeline re-touching a
    document already seen) never duplicates a row. When the row already
    exists, extracted keys are UNION-merged (never lost), matching
    ``upsert_afectado``'s "never overwrite a present value" discipline in
    ``services/oportunidades.py``.
    """
    claves = claves or extraer_claves(texto or "", titulo)

    existing = db.execute(select(HistoricoDoc).where(HistoricoDoc.boe_id == boe_id)).scalar_one_or_none()

    if existing:
        existing.identificadores = _merge_listas(existing.identificadores, claves.identificadores)
        existing.matriculas = _merge_listas(existing.matriculas, claves.matriculas)
        existing.nombres = _merge_listas(existing.nombres, claves.nombres)
        existing.digitos_parciales = _merge_listas(existing.digitos_parciales, claves.digitos_parciales)
        if claves.nombres_norm and not existing.nombres_norm:
            existing.nombres_norm = claves.nombres_norm
        elif claves.nombres_norm and claves.nombres_norm not in existing.nombres_norm:
            existing.nombres_norm = f"{existing.nombres_norm} zzsep {claves.nombres_norm}".strip()
        if guardar_texto and texto and not existing.texto_plano:
            existing.texto_plano = texto[:50_000]
            existing.hash_texto = hash_text(texto)
        if not existing.extracto and texto:
            existing.extracto = texto[:EXTRACTO_MAX_CHARS]
        for attr, value in (
            ("url_html", url_html), ("url_xml", url_xml), ("url_pdf", url_pdf),
            ("departamento_nombre", departamento_nombre), ("seccion_codigo", seccion_codigo),
        ):
            if value and not getattr(existing, attr):
                setattr(existing, attr, value)
        return existing, False

    doc = HistoricoDoc(
        boe_id=boe_id,
        fuente=fuente,
        fecha_publicacion=fecha_publicacion,
        seccion_codigo=seccion_codigo,
        departamento_nombre=departamento_nombre,
        titulo=titulo,
        url_html=url_html,
        url_xml=url_xml,
        url_pdf=url_pdf,
        texto_plano=(texto[:50_000] if (guardar_texto and texto) else None),
        extracto=(texto[:EXTRACTO_MAX_CHARS] if texto else None),
        hash_texto=hash_text(texto) if texto else None,
        identificadores=claves.identificadores,
        matriculas=claves.matriculas,
        nombres=claves.nombres,
        digitos_parciales=claves.digitos_parciales,
        nombres_norm=claves.nombres_norm,
        familia_sancionadora=familia_sancionadora,
        confidence=confidence,
        origen_indexado=origen_indexado,
    )
    db.add(doc)
    db.flush()
    return doc, True


def upsert_from_doc_data(
    db: Session,
    doc_data: dict[str, Any],
    texto: str | None,
    *,
    fuente: str = "boe",
    origen_indexado: str = "diario",
    familia_sancionadora: str | None = None,
    confidence: float | None = None,
    guardar_texto: bool = False,
) -> tuple[HistoricoDoc, bool] | None:
    """Convenience wrapper over the ``doc_data`` shape produced by
    ``boe_client.flatten_sumario``/``teu_client.parse_teu_index``."""
    boe_id = doc_data.get("identificador")
    fecha = doc_data.get("fecha_publicacion")
    titulo = doc_data.get("titulo")
    if not boe_id or not fecha or not titulo:
        return None
    return upsert_historico_doc(
        db,
        boe_id=boe_id,
        fuente=fuente,
        fecha_publicacion=fecha,
        titulo=titulo,
        origen_indexado=origen_indexado,
        seccion_codigo=doc_data.get("seccion_codigo"),
        departamento_nombre=doc_data.get("departamento_nombre"),
        url_html=doc_data.get("url_html"),
        url_xml=doc_data.get("url_xml"),
        url_pdf=doc_data.get("url_pdf"),
        texto=texto,
        familia_sancionadora=familia_sancionadora,
        confidence=confidence,
        guardar_texto=guardar_texto,
    )
