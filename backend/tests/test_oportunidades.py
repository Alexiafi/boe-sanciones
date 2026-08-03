from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from app.models.documento import BoeDocumento
from app.models.sancionado import Sancionado
from app.schemas.sancionado import SancionadoUpdate
from app.services.extractor import AfectadoExtraido
from app.services.oportunidades import allocate_codigo, build_origen_clave, extracted_values, has_substantive_data, upsert_afectado
from app.database import SyncSessionLocal


def test_schema_and_update_contract():
    columns = set(Sancionado.__table__.c.keys())
    assert {"codigo", "estado_oportunidad", "origen_clave", "localidad", "importe_deuda_eur", "fecha_resolucion"}.issubset(columns)
    assert SancionadoUpdate(telefono=" +34 600 123 456 ").telefono == "+34 600 123 456"
    assert SancionadoUpdate(email=" ").email is None


def test_key_and_mapping_are_stable():
    affected = AfectadoExtraido(identificador="A123", localidad="Madrid", importe_deuda_eur=42.5, fecha_resolucion=date(2026, 8, 1))
    assert has_substantive_data(affected)
    assert build_origen_clave("BOE-2026-X", affected) == build_origen_clave("BOE-2026-X", affected)
    values = extracted_values(affected)
    assert values["localidad"] == "Madrid"
    assert values["fecha_resolucion"] == date(2026, 8, 1)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL_SYNC"),
    reason="requiere TEST_DATABASE_URL_SYNC (PostgreSQL efímero)",
)
def test_annual_codes_and_idempotent_upsert(clean_database):
    session = SyncSessionLocal()
    try:
        document = BoeDocumento(boe_id="BOE-2026-TEST", fecha_publicacion=date(2026, 8, 1), titulo="Prueba")
        session.add(document)
        session.flush()
        affected = AfectadoExtraido(identificador="X123", importe_multa_eur=100)
        first, created = upsert_afectado(session, document, affected)
        assert created and first is not None and first.codigo == "OP-2026-000001"
        second, created = upsert_afectado(session, document, affected)
        assert not created and second.id == first.id
        assert allocate_codigo(session, 2027) == "OP-2027-000001"
    finally:
        session.rollback()
        session.close()


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL_SYNC"),
    reason="requiere TEST_DATABASE_URL_SYNC (PostgreSQL efímero)",
)
def test_annual_code_allocation_is_concurrent_safe(clean_database):
    def allocate() -> str:
        session = SyncSessionLocal()
        try:
            code = allocate_codigo(session, 2028)
            session.commit()
            return code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: allocate(), range(2)))
    assert set(codes) == {"OP-2028-000001", "OP-2028-000002"}
