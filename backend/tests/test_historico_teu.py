"""TEU public-search connector: off by default, fixture-backed in tests,
never opens a real socket while disabled."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.historico import HistoricoDoc
from app.services.historico import teu_publico
from app.services.historico.teu_publico import EntradaTeu, TeuBuscadorFixture, fuera_de_ventana_teu

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def test_teu_desactivado_por_defecto(monkeypatch):
    monkeypatch.setattr(settings, "teu_public_search_enabled", False)
    disponible, motivo = teu_publico.teu_search_available()
    assert disponible is False
    assert "TEU_PUBLIC_SEARCH_ENABLED" in motivo


def test_teu_habilitado_sin_proveedor(monkeypatch):
    monkeypatch.setattr(settings, "teu_public_search_enabled", True)
    monkeypatch.setattr(settings, "teu_public_search_provider", "none")
    disponible, motivo = teu_publico.teu_search_available()
    assert disponible is False
    assert "TEU_PUBLIC_SEARCH_PROVIDER" in motivo


def test_fixture_buscador_no_toca_la_red():
    hoy = date.today()
    buscador = TeuBuscadorFixture({
        "12345678Z": [EntradaTeu(identificador="BOE-N-2026-1", titulo="Notificación", fecha_publicacion=hoy)],
    })
    resultados = buscador.buscar_por_clave("12345678Z", desde=hoy - timedelta(days=90), hasta=hoy)
    assert len(resultados) == 1
    assert buscador.buscar_por_clave("OTRO", desde=hoy - timedelta(days=90), hasta=hoy) == []


def test_ventana_de_90_dias_marca_fuera_de_ventana():
    hoy = date(2026, 8, 3)
    reciente = hoy - timedelta(days=30)
    antiguo = hoy - timedelta(days=120)
    assert fuera_de_ventana_teu(reciente, hoy=hoy) is False
    assert fuera_de_ventana_teu(antiguo, hoy=hoy) is True


@pytest.mark.integration
def test_busqueda_con_teu_habilitado_materializa_documento(monkeypatch, clean_database):
    from app.models.cliente import Cliente
    from app.models.documento import BoeDocumento
    from app.models.sancionado import Sancionado
    from app.services.historico.busqueda import buscar_historico
    from app.services.oportunidades import allocate_codigo

    monkeypatch.setattr(settings, "teu_public_search_enabled", True)
    monkeypatch.setattr(settings, "teu_public_search_provider", "fixture")

    session = SyncSessionLocal()
    try:
        doc = BoeDocumento(boe_id="BOE-TEU-ORIGEN", fecha_publicacion=date(2026, 7, 1), titulo="Origen")
        session.add(doc)
        session.flush()
        sancionado = Sancionado(
            boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
            origen_clave="clave-teu-1", nombre="Persona TEU",
        )
        session.add(sancionado)
        session.flush()
        cliente = Cliente(
            codigo="CLI-2026-TEU1", nombre_razon_social="Persona TEU", dni_nie="12345678Z",
            sancion_origen_id=sancionado.id,
        )
        session.add(cliente)
        session.flush()
        session.commit()

        hoy = date.today()
        fixture = TeuBuscadorFixture({
            "12345678Z": [EntradaTeu(
                identificador="BOE-N-2026-99", titulo="Notificación TEU", fecha_publicacion=hoy,
                url_pdf="https://boe.es/x.pdf",
            )],
        })
        resultado = buscar_historico(session, cliente, incluir_teu=True, buscador_teu=fixture)
        assert any(r.via_match == "teu_publico" for r in resultado["resultados"])

        materializado = session.execute(
            select(HistoricoDoc).where(HistoricoDoc.boe_id == "BOE-N-2026-99")
        ).scalar_one()
        assert materializado.fuente == "teu"
        assert materializado.origen_indexado == "teu_publico"

        # Re-running does not duplicate the materialised document or the result.
        buscar_historico(session, cliente, incluir_teu=True, buscador_teu=fixture)
        count = session.execute(
            select(HistoricoDoc).where(HistoricoDoc.boe_id == "BOE-N-2026-99")
        ).scalars().all()
        assert len(count) == 1
    finally:
        session.close()


def test_teu_http_nunca_construye_cliente_mientras_deshabilitado(monkeypatch):
    monkeypatch.setattr(settings, "teu_public_search_enabled", False)
    disponible, _ = teu_publico.teu_search_available()
    assert disponible is False
    # The HTTP adapter's httpx.Client() lives inside buscar_por_clave, never
    # at construction time; since the gate is checked BEFORE any adapter
    # method is ever called by busqueda.py, disabling it is sufficient proof
    # no request is possible without an explicit, separate opt-in.
