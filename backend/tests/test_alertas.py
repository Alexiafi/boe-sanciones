"""Free daily radar over the historical index (services/alertas.py) — the
detection path that works even with OPENAI_EXTRACTION_ENABLED=false."""

from __future__ import annotations

from datetime import date
import os

import pytest

from sqlalchemy import select

from app.database import SyncSessionLocal
from app.models.cliente import Cliente
from app.models.documento import BoeDocumento
from app.models.notificacion import Notificacion
from app.models.sancionado import Sancionado
from app.services.alertas import ejecutar_radar_clientes
from app.services.historico.indexado import upsert_historico_doc
from app.services.historico.patterns import extraer_claves
from app.services.oportunidades import allocate_codigo

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _cliente_activo(session, *, suffix: str, cif_nif: str, estado_cliente: str = "activo") -> Cliente:
    doc = BoeDocumento(boe_id=f"BOE-ALE-{suffix}", fecha_publicacion=date(2026, 7, 1), titulo="Origen")
    session.add(doc)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
        origen_clave=f"clave-ale-{suffix}", nombre="Acme Logistica SL",
    )
    session.add(sancionado)
    session.flush()
    cliente = Cliente(
        codigo=f"CLI-2026-ALE{suffix}", nombre_razon_social="Acme Logistica SL",
        cif_nif=cif_nif, sancion_origen_id=sancionado.id, estado_cliente=estado_cliente,
    )
    session.add(cliente)
    session.flush()
    return cliente


@pytest.mark.integration
def test_radar_alerta_solo_matches_nuevos_de_alta_confianza(clean_database):
    session = SyncSessionLocal()
    try:
        # B12345674 is a checksum-valid CIF (see test_historico_busqueda.py) —
        # extraer_claves only picks up identifiers that pass the CIF/DNI
        # checksum, so the exact-match path needs a real one, not an
        # arbitrary string.
        cliente = _cliente_activo(session, suffix="1", cif_nif="B12345674")
        texto = "Sancionada ACME LOGISTICA SL con CIF B12345674 por infraccion."
        claves = extraer_claves(texto, "Sancion Acme")
        upsert_historico_doc(
            session, boe_id="BOE-ALE-DOC-1", fuente="boe", fecha_publicacion=date(2026, 8, 1),
            titulo="Sancion Acme", origen_indexado="diario", texto=texto, claves=claves,
        )
        session.commit()
        cliente_id = cliente.id

        stats = ejecutar_radar_clientes(session)
        assert stats["clientes_revisados"] == 1
        assert stats["alertas_creadas"] == 1

        notifs = session.execute(
            select(Notificacion).where(Notificacion.cliente_id == cliente_id)
        ).scalars().all()
        assert len(notifs) == 1
        assert notifs[0].tipo == "nueva_sancion_cliente"

        # Idempotent: the match already exists, so a second run creates nothing new.
        segunda = ejecutar_radar_clientes(session)
        assert segunda["alertas_creadas"] == 0
        assert session.execute(
            select(Notificacion).where(Notificacion.cliente_id == cliente_id)
        ).scalars().all().__len__() == 1
    finally:
        session.close()


@pytest.mark.integration
def test_radar_ignora_clientes_inactivos(clean_database):
    session = SyncSessionLocal()
    try:
        _cliente_activo(session, suffix="2", cif_nif="B87654321", estado_cliente="inactivo")
        texto = "Sancionada con CIF B87654321."
        claves = extraer_claves(texto, "Sancion inactivo")
        upsert_historico_doc(
            session, boe_id="BOE-ALE-DOC-2", fuente="boe", fecha_publicacion=date(2026, 8, 1),
            titulo="Sancion inactivo", origen_indexado="diario", texto=texto, claves=claves,
        )
        session.commit()

        stats = ejecutar_radar_clientes(session)
        assert stats["clientes_revisados"] == 0
        assert stats["alertas_creadas"] == 0
        assert session.execute(select(Notificacion)).scalars().all() == []
    finally:
        session.close()


@pytest.mark.integration
def test_radar_no_alerta_por_match_debil_solo_nombre(clean_database):
    session = SyncSessionLocal()
    try:
        cliente = _cliente_activo(session, suffix="3", cif_nif="B11122233")
        # Only a weak name-based match (no CIF/DNI/matrícula in the text) — must not alert.
        texto = "Nombrada en el listado ACME LOGISTICA SL entre otras entidades."
        claves = extraer_claves(texto, "Listado general")
        upsert_historico_doc(
            session, boe_id="BOE-ALE-DOC-3", fuente="boe", fecha_publicacion=date(2026, 8, 1),
            titulo="Listado general", origen_indexado="diario", texto=texto, claves=claves,
        )
        session.commit()

        stats = ejecutar_radar_clientes(session)
        assert stats["alertas_creadas"] == 0
        assert session.execute(
            select(Notificacion).where(Notificacion.cliente_id == cliente.id)
        ).scalars().all() == []
    finally:
        session.close()
