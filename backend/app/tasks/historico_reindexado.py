"""Free re-indexing of documents the daily pipeline already downloaded.

The daily accumulation into ``historico_docs`` (``tasks/scraping.py``) only
exists since session 3; every ``BoeDocumento`` ingested before that — and
any document whose indexing failed mid-run — has its text in
``boe_documentos.texto_plano`` but no row in the historical index, so the
"Consulta por DNI/CIF" screen cannot find identifiers that the 30-day panel
plainly shows. This task closes that gap with zero network and zero OpenAI:
it is pure regex over text already on disk (``historico/indexado.py``).

Idempotent (``upsert_historico_doc`` keys on ``boe_id``) and safe to run
any time; exposed as ``POST /api/historico/reindexar`` and run once
automatically on worker start-up.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_, select

from app.celery_app import celery
from app.database import SyncSessionLocal
from app.models.documento import BoeDocumento
from app.models.historico import HistoricoDoc
from app.services.historico.indexado import upsert_historico_doc

logger = logging.getLogger(__name__)

LOTE = 200


def _no_manual():
    return or_(BoeDocumento.source.is_(None), BoeDocumento.source != "manual")


def _fuente(document: BoeDocumento) -> str:
    if document.boe_id.startswith("BOE-N-") or (document.seccion_codigo or "").upper() == "TEU":
        return "teu"
    return "boe"


def reindexar_documentos_descargados(db, *, limite: int | None = None) -> dict[str, int]:
    """Index every non-manual ``BoeDocumento`` that has text but no
    ``HistoricoDoc`` yet. Commits per batch of ``LOTE`` so an interruption
    keeps what it already did."""
    stats = {"vistos": 0, "indexados": 0, "sin_texto": 0}
    indexados_ids = select(HistoricoDoc.boe_id)
    query = (
        select(BoeDocumento)
        .where(BoeDocumento.boe_id.not_in(indexados_ids), _no_manual())
        .order_by(BoeDocumento.fecha_publicacion.desc(), BoeDocumento.id)
    )
    if limite:
        query = query.limit(limite)
    pendientes = db.execute(query).scalars().all()
    for index, document in enumerate(pendientes, start=1):
        stats["vistos"] += 1
        if not document.texto_plano:
            stats["sin_texto"] += 1
            continue
        _doc, creado = upsert_historico_doc(
            db,
            boe_id=document.boe_id,
            fuente=_fuente(document),
            fecha_publicacion=document.fecha_publicacion,
            titulo=document.titulo,
            origen_indexado="diario",
            seccion_codigo=document.seccion_codigo,
            departamento_nombre=document.departamento_nombre,
            url_html=document.url_html,
            url_xml=document.url_xml,
            url_pdf=document.url_pdf,
            texto=document.texto_plano,
            familia_sancionadora=document.familia_sancionadora,
            confidence=document.confidence,
            guardar_texto=True,
        )
        if creado:
            stats["indexados"] += 1
        if index % LOTE == 0:
            db.commit()
    db.commit()
    logger.info("Reindexado histórico: %s", stats)
    return stats


def pendientes_de_reindexar(db) -> int:
    indexados_ids = select(HistoricoDoc.boe_id)
    return int(
        db.execute(
            select(func.count(BoeDocumento.id)).where(
                BoeDocumento.boe_id.not_in(indexados_ids), _no_manual(),
                BoeDocumento.texto_plano.is_not(None),
            )
        ).scalar_one()
    )


@celery.task(name="app.tasks.historico_reindexado.reindexar_task")
def reindexar_task(limite: int | None = None) -> dict[str, Any]:
    db = SyncSessionLocal()
    try:
        return reindexar_documentos_descargados(db, limite=limite)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
