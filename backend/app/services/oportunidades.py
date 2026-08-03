"""Persistence helpers for the opportunity core.

All functions in this module are synchronous because the scraping worker uses the
synchronous SQLAlchemy session. API writes remain in their async router.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.models.codigo_oportunidad import CodigoOportunidadContador
from app.models.sancionado import Sancionado


OPPORTUNITY_STATES = ("nueva", "revisada", "contactada", "descartada", "cliente")


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def build_origen_clave(boe_id: str, data: Any) -> str:
    """Return a stable SHA-256 key for one extracted affected party."""
    parts = (
        boe_id,
        getattr(data, "identificador", None),
        getattr(data, "nombre", None),
        getattr(data, "expediente", None),
        getattr(data, "matricula_coche", None),
        getattr(data, "tipo_procedimiento", None),
    )
    payload = "\x1f".join(_normalise(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def has_substantive_data(data: Any) -> bool:
    return any(
        _normalise(getattr(data, field, None))
        for field in ("nombre", "identificador", "expediente", "matricula_coche", "razon_sancion")
    )


def allocate_codigo(session, publication_year: int) -> str:
    """Allocate the next annual OP code atomically in PostgreSQL."""
    stmt = (
        insert(CodigoOportunidadContador)
        .values(anio=publication_year, ultimo_valor=1)
        .on_conflict_do_update(
            index_elements=[CodigoOportunidadContador.anio],
            set_={"ultimo_valor": CodigoOportunidadContador.ultimo_valor + 1},
        )
        .returning(CodigoOportunidadContador.ultimo_valor)
    )
    sequence = session.execute(stmt).scalar_one()
    return f"OP-{publication_year}-{sequence:06d}"


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def extracted_values(data: Any) -> dict[str, Any]:
    """Map structured extractor data to persisted opportunity fields."""
    values = {
        "nombre": data.nombre,
        "tipo_persona": data.tipo_persona,
        "identificador": data.identificador,
        "tipo_identificador": data.tipo_identificador,
        "direccion": data.direccion,
        "localidad": data.localidad,
        "provincia": data.provincia,
        "codigo_postal": data.codigo_postal,
        "telefono": data.telefono,
        "email": data.email,
        "matricula_coche": data.matricula_coche,
        "importe_multa_eur": data.importe_multa_eur,
        "tipo_infraccion": data.tipo_infraccion,
        "razon_sancion": data.razon_sancion,
        "expediente": data.expediente,
        "estado_publicacion": data.estado_publicacion,
        "tipo_procedimiento": data.tipo_procedimiento,
        "importe_deuda_eur": data.importe_deuda_eur,
        "plazo_notificacion": data.plazo_notificacion,
        "plazo_alegaciones": data.plazo_alegaciones,
        "plazo_recurso": data.plazo_recurso,
        "plazo_pago_voluntario": data.plazo_pago_voluntario,
        "base_legal": data.base_legal,
        "organismo_emisor": data.organismo_emisor,
        "dominio_material": data.dominio_material,
        "fecha_resolucion": _as_date(data.fecha_resolucion),
        "observaciones": data.observaciones,
    }
    return {key: value for key, value in values.items() if value not in (None, "")}


def upsert_afectado(session, boe_doc, data: Any) -> tuple[Sancionado | None, bool]:
    """Create an opportunity once, or only fill missing extracted fields on replay."""
    if not has_substantive_data(data):
        return None, False

    origen_clave = build_origen_clave(boe_doc.boe_id, data)
    existing = session.query(Sancionado).filter_by(origen_clave=origen_clave).one_or_none()
    values = extracted_values(data)
    if existing:
        # Contact values can be manually curated; never replace a present value.
        for key, value in values.items():
            if getattr(existing, key) in (None, ""):
                setattr(existing, key, value)
        return existing, False

    opportunity = Sancionado(
        boe_document_id=boe_doc.id,
        codigo=allocate_codigo(session, boe_doc.fecha_publicacion.year),
        estado_oportunidad="nueva",
        origen_clave=origen_clave,
        **values,
    )
    session.add(opportunity)
    session.flush()
    return opportunity, True
