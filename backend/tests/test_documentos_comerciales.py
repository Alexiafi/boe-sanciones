"""Contract/invoice generation: explicit missing-field validation, atomic
numbering, and real (locally-rendered, zero-cost) PDF output."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SyncSessionLocal
from app.models.cliente import Cliente
from app.models.documentos_comerciales import ContadorFactura
from app.services.documentos_comerciales import (
    DatosFaltantesError,
    allocate_numero_factura,
    generar_contrato,
    generar_factura,
    validar,
)
from app.services.parser import pdf_to_text

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


def _cliente(session, sufijo: str, **overrides) -> Cliente:
    from app.models.sancionado import Sancionado
    from app.models.documento import BoeDocumento
    from app.services.oportunidades import allocate_codigo

    doc = BoeDocumento(boe_id=f"BOE-DOC-{sufijo}", fecha_publicacion=date(2026, 1, 1), titulo="Origen")
    session.add(doc)
    session.flush()
    sancionado = Sancionado(
        boe_document_id=doc.id, codigo=allocate_codigo(session, 2026), estado_oportunidad="cliente",
        origen_clave=f"doc-clave-{sufijo}", nombre="Cliente Documentos SL",
    )
    session.add(sancionado)
    session.flush()
    cliente = Cliente(
        codigo=f"CLI-2026-DOC{sufijo}", nombre_razon_social="Cliente Documentos SL",
        cif_nif=overrides.get("cif_nif", "B12345674"),
        direccion_fiscal=overrides.get("direccion_fiscal", "Calle Falsa 123, Madrid"),
        email=overrides.get("email"),
        sancion_origen_id=sancionado.id,
    )
    session.add(cliente)
    session.flush()
    return cliente


def _configurar_emisor(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "emisor_nombre", "Despacho Judit SL")
    monkeypatch.setattr(settings, "emisor_cif", "B99999999")
    monkeypatch.setattr(settings, "emisor_direccion", "Gran Vía 1, Madrid")
    monkeypatch.setattr(settings, "emisor_iva_porcentaje", 21.0)
    monkeypatch.setattr(settings, "factura_serie", "FAC")
    monkeypatch.setattr(settings, "documentos_dir", str(tmp_path))


@pytest.mark.integration
def test_validar_devuelve_campos_exactos_faltantes(monkeypatch, tmp_path, clean_database):
    session = SyncSessionLocal()
    try:
        # Emisor NOT configured, cliente missing direccion_fiscal.
        monkeypatch.setattr(settings, "emisor_nombre", "")
        monkeypatch.setattr(settings, "emisor_cif", "")
        monkeypatch.setattr(settings, "emisor_direccion", "")
        monkeypatch.setattr(settings, "factura_serie", "")
        cliente = _cliente(session, "1", direccion_fiscal=None)
        session.commit()

        faltantes = validar(session, "factura", cliente, {})
        campos = {f.campo for f in faltantes}
        assert "EMISOR_NOMBRE" in campos
        assert "EMISOR_CIF" in campos
        assert "EMISOR_DIRECCION" in campos
        assert "FACTURA_SERIE" in campos
        assert "cliente.direccion_fiscal" in campos
        assert "cuantia" in campos
        assert "concepto" in campos
    finally:
        session.close()


@pytest.mark.integration
def test_generar_contrato_produce_pdf_real_con_cif_y_precio(monkeypatch, tmp_path, clean_database):
    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, "2")
        session.commit()

        documento = generar_contrato(session, cliente, precio=1500.0)
        assert documento.tipo == "contrato"
        assert documento.datos["precio"] == 1500.0
        assert documento.datos["plantilla_provisional"] is True  # seeded template, not yet overridden

        with open(documento.pdf_path, "rb") as fh:
            contenido = fh.read()
        assert contenido[:4] == b"%PDF"
        # The CIF and formatted price must actually appear in the rendered PDF text.
        texto = pdf_to_text(contenido)
        assert "B12345674" in texto
        assert "1.500,00" in texto or "1500" in texto
    finally:
        session.close()


@pytest.mark.integration
def test_generar_factura_falla_con_datos_incompletos(monkeypatch, tmp_path, clean_database):
    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, "3")
        session.commit()
        with pytest.raises(DatosFaltantesError) as exc_info:
            generar_factura(session, cliente, cuantia=0, concepto="")
        campos = {f.campo for f in exc_info.value.faltantes}
        assert "cuantia" in campos
        assert "concepto" in campos
    finally:
        session.close()


@pytest.mark.integration
def test_generar_factura_numera_correlativamente_y_calcula_iva(monkeypatch, tmp_path, clean_database):
    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    try:
        cliente = _cliente(session, "4")
        session.commit()

        primera = generar_factura(session, cliente, cuantia=100.0, concepto="Servicio A")
        segunda = generar_factura(session, cliente, cuantia=200.0, concepto="Servicio B")

        assert primera.numero != segunda.numero
        assert primera.numero.startswith("FAC-")
        assert primera.datos["iva_importe"] == 21.0
        assert primera.datos["total"] == 121.0

        with open(segunda.pdf_path, "rb") as fh:
            assert fh.read()[:4] == b"%PDF"
    finally:
        session.close()


@pytest.mark.integration
def test_numeracion_factura_es_segura_bajo_concurrencia(clean_database):
    session = SyncSessionLocal()
    try:
        numeros: list[str] = []

        def _allocate(_i):
            local_session = SyncSessionLocal()
            try:
                numero = allocate_numero_factura(local_session, "FAC", 2026)
                local_session.commit()
                return numero
            finally:
                local_session.close()

        with ThreadPoolExecutor(max_workers=8) as pool:
            numeros = list(pool.map(_allocate, range(8)))

        assert len(set(numeros)) == 8  # every number unique, none dropped or duplicated
        contador = session.execute(
            select(ContadorFactura).where(ContadorFactura.serie == "FAC", ContadorFactura.anio == 2026)
        ).scalar_one()
        assert contador.ultimo_valor == 8
    finally:
        session.close()


@pytest.mark.integration
def test_no_se_genera_sin_plantilla_activa(monkeypatch, tmp_path, clean_database):
    from app.models.documentos_comerciales import PlantillaDocumento

    _configurar_emisor(monkeypatch, tmp_path)
    session = SyncSessionLocal()
    try:
        session.execute(PlantillaDocumento.__table__.update().where(PlantillaDocumento.tipo == "contrato").values(activo=False))
        session.commit()
        cliente = _cliente(session, "5")
        session.commit()
        with pytest.raises(DatosFaltantesError) as exc_info:
            generar_contrato(session, cliente, precio=100.0)
        assert any(f.campo == "plantilla" for f in exc_info.value.faltantes)
    finally:
        session.execute(PlantillaDocumento.__table__.update().where(PlantillaDocumento.tipo == "contrato").values(activo=True))
        session.commit()
        session.close()
