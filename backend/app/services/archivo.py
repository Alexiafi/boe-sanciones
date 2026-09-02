"""Idempotent archive of original BOE/TEU document bytes.

The BOE notifications supplement and the TEU remove documents from their
public sites after a period; keeping the exact bytes we downloaded is what
lets the product show the original document long after the source link died.
Writes are idempotent on ``boe_id`` — the first copy archived wins and is
never overwritten — and capped in size so one pathological document cannot
bloat the database. ``db.add`` without flush: the row commits together with
the document it belongs to.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.archivo import DocumentoArchivo

logger = logging.getLogger(__name__)

MAX_ARCHIVO_BYTES = 2_000_000


def guardar_archivo(
    db: Session,
    *,
    boe_id: str,
    content_type: str,
    contenido: bytes,
    url_origen: str | None = None,
) -> bool:
    """Archive the raw document once. Returns False when skipped."""
    if not contenido:
        return False
    if len(contenido) > MAX_ARCHIVO_BYTES:
        logger.warning(
            "Archivo de %s descartado: %d bytes supera el tope de %d",
            boe_id, len(contenido), MAX_ARCHIVO_BYTES,
        )
        return False
    exists = db.execute(
        select(DocumentoArchivo.id).where(DocumentoArchivo.boe_id == boe_id)
    ).scalar_one_or_none()
    if exists is not None:
        return False
    db.add(DocumentoArchivo(
        boe_id=boe_id, content_type=content_type, contenido=contenido,
        bytes=len(contenido), url_origen=url_origen,
    ))
    return True
