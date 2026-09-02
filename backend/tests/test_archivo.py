"""Archivo local del documento original: servicio, pipeline y endpoints.

Garantiza que el PDF/HTML/XML descargado queda archivado en
``documento_archivos`` (idempotente, con tope de tamaño) y que los endpoints
lo sirven — con el texto extraído como respaldo — para que un documento siga
visible aunque la fuente (suplemento de notificaciones, TEU) lo retire.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SyncSessionLocal
from app.main import app
from app.models.archivo import DocumentoArchivo
from app.models.documento import BoeDocumento
from app.models.historico import HistoricoDoc
from app.models.sancionado import Sancionado
from app.services.archivo import MAX_ARCHIVO_BYTES, guardar_archivo
from app.services.oportunidades import allocate_codigo
from app.tasks import scraping

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")


@pytest.mark.integration
def test_guardar_archivo_es_idempotente_y_con_tope(clean_database):
    session = SyncSessionLocal()
    try:
        assert guardar_archivo(session, boe_id="BOE-ARCH-1", content_type="application/pdf", contenido=b"%PDF-1.4 datos") is True
        session.commit()
        # Mismo boe_id: nunca duplica ni sobrescribe la primera copia.
        assert guardar_archivo(session, boe_id="BOE-ARCH-1", content_type="application/pdf", contenido=b"otro") is False
        assert guardar_archivo(session, boe_id="BOE-ARCH-2", content_type="application/pdf", contenido=b"") is False
        assert guardar_archivo(session, boe_id="BOE-ARCH-3", content_type="application/pdf", contenido=b"x" * (MAX_ARCHIVO_BYTES + 1)) is False
        session.commit()

        filas = session.execute(select(DocumentoArchivo)).scalars().all()
        assert len(filas) == 1
        assert filas[0].contenido == b"%PDF-1.4 datos"
        assert filas[0].bytes == len(b"%PDF-1.4 datos")
    finally:
        session.close()


@pytest.mark.integration
def test_pipeline_archiva_el_bruto_y_guarda_texto_en_historico(monkeypatch, clean_database):
    document = {
        "identificador": "BOE-ARCH-PIPE", "fecha_publicacion": date(2026, 8, 3),
        "titulo": "Documento archivado", "seccion_codigo": "3",
        "url_html": "https://www.boe.es/doc.html",
    }
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "classify_document", lambda _: (True, ["fixture"], 0.95, "sancion_firme"))
    monkeypatch.setattr(scraping, "verify_with_body", lambda _: (True, ["fixture"]))
    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [document],
        fetch_text=lambda _: ("texto plano", "html", ("text/html", b"<html>cuerpo</html>", "https://www.boe.es/doc.html")),
        send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "", parse_teu_index=lambda *_: [], filter_teu_entries=lambda _: [], fetch_teu_pdf=lambda _: b"",
    )
    scraping.run_scraping("2026-08-03", dependencies=deps)

    session = SyncSessionLocal()
    try:
        archivo = session.execute(
            select(DocumentoArchivo).where(DocumentoArchivo.boe_id == "BOE-ARCH-PIPE")
        ).scalar_one()
        assert archivo.content_type == "text/html"
        assert archivo.contenido == b"<html>cuerpo</html>"
        assert archivo.url_origen == "https://www.boe.es/doc.html"

        historico = session.execute(
            select(HistoricoDoc).where(HistoricoDoc.boe_id == "BOE-ARCH-PIPE")
        ).scalar_one()
        assert historico.texto_plano == "texto plano"
    finally:
        session.close()


@pytest.mark.integration
def test_pipeline_archiva_pdf_teu(monkeypatch, clean_database):
    teu_entry = {
        "identificador": "BOE-N-ARCH-TEU", "fecha_publicacion": date(2026, 8, 3),
        "titulo": "Notificación TEU", "url_pdf": "https://sede.example/doc.pdf",
        "departamento_nombre": None,
    }
    monkeypatch.setattr(scraping, "should_skip_section", lambda _: False)
    monkeypatch.setattr(scraping, "pdf_to_text", lambda _: "contenido teu")
    deps = scraping.PipelineDependencies(
        fetch_sumario=lambda _: {}, flatten_sumario=lambda *_: [],
        send_digest=lambda *_: None, notify=lambda *_: None,
        fetch_teu_index=lambda _: "idx", parse_teu_index=lambda *_: [teu_entry],
        filter_teu_entries=lambda entries: entries, fetch_teu_pdf=lambda _: b"%PDF-teu",
    )
    scraping.run_scraping("2026-08-03", dependencies=deps)

    session = SyncSessionLocal()
    try:
        archivo = session.execute(
            select(DocumentoArchivo).where(DocumentoArchivo.boe_id == "BOE-N-ARCH-TEU")
        ).scalar_one()
        assert archivo.content_type == "application/pdf"
        assert archivo.contenido == b"%PDF-teu"
    finally:
        session.close()


@pytest.mark.integration
def test_endpoint_documento_archivo_sirve_bytes_texto_o_404(clean_database):
    session = SyncSessionLocal()
    try:
        doc_bin = BoeDocumento(boe_id="BOE-ARCH-EP1", fecha_publicacion=date(2026, 4, 1), titulo="Con binario")
        doc_txt = BoeDocumento(boe_id="BOE-ARCH-EP2", fecha_publicacion=date(2026, 4, 1), titulo="Solo texto", texto_plano="texto plano archivado")
        doc_sin = BoeDocumento(boe_id="BOE-ARCH-EP3", fecha_publicacion=date(2026, 4, 1), titulo="Sin copia")
        session.add_all([doc_bin, doc_txt, doc_sin])
        session.flush()
        session.add(DocumentoArchivo(
            boe_id="BOE-ARCH-EP1", content_type="application/pdf",
            contenido=b"%PDF-binario", bytes=len(b"%PDF-binario"),
        ))
        session.commit()
        ids = {d.boe_id: d.id for d in (doc_bin, doc_txt, doc_sin)}
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get(f"/api/documentos/{ids['BOE-ARCH-EP1']}/archivo")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-binario"
        assert 'filename="BOE-ARCH-EP1.pdf"' in resp.headers["content-disposition"]

        resp = client.get(f"/api/documentos/{ids['BOE-ARCH-EP2']}/archivo")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert resp.text == "texto plano archivado"

        assert client.get(f"/api/documentos/{ids['BOE-ARCH-EP3']}/archivo").status_code == 404
        assert client.get("/api/documentos/999999/archivo").status_code == 404


@pytest.mark.integration
def test_endpoint_historico_archivo_y_flag_en_listado(clean_database):
    session = SyncSessionLocal()
    try:
        con_extracto = HistoricoDoc(
            boe_id="BOE-ARCH-H1", fuente="teu", fecha_publicacion=date(2026, 5, 1),
            titulo="TEU con extracto", extracto="extracto del documento",
        )
        session.add(con_extracto)
        session.commit()
        doc_id = con_extracto.id
    finally:
        session.close()

    with TestClient(app) as client:
        resp = client.get(f"/api/historico/{doc_id}/archivo")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert resp.text == "extracto del documento"

        resp = client.get("/api/historico", params={"fuente": "teu"})
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["boe_id"] == "BOE-ARCH-H1")
        assert item["tiene_copia_local"] is True

        assert client.get("/api/historico/999999/archivo").status_code == 404


@pytest.mark.integration
def test_detalle_sancion_expone_tiene_copia_local(clean_database):
    session = SyncSessionLocal()
    try:
        doc = BoeDocumento(boe_id="BOE-ARCH-S1", fecha_publicacion=date(2026, 6, 1), titulo="Doc sanción")
        session.add(doc)
        session.flush()
        sancionado = Sancionado(
            boe_document_id=doc.id, codigo=allocate_codigo(session, 2026),
            estado_oportunidad="nueva", origen_clave="clave-arch-s1",
        )
        session.add(sancionado)
        session.commit()
        sancionado_id = sancionado.id
    finally:
        session.close()

    # One TestClient for the whole test: each client spins its own event loop
    # and the pooled asyncpg connections cannot cross loops (see conftest).
    with TestClient(app) as client:
        resp = client.get(f"/api/sanciones/{sancionado_id}")
        assert resp.status_code == 200
        assert resp.json()["tiene_copia_local"] is False

        session = SyncSessionLocal()
        try:
            session.add(DocumentoArchivo(
                boe_id="BOE-ARCH-S1", content_type="application/pdf",
                contenido=b"%PDF-sancion", bytes=len(b"%PDF-sancion"),
            ))
            session.commit()
        finally:
            session.close()

        resp = client.get(f"/api/sanciones/{sancionado_id}")
        assert resp.status_code == 200
        assert resp.json()["tiene_copia_local"] is True
