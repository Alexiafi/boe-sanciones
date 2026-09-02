"""Backfill tests: a tiny SIMULATED 3-day range via inline fixtures. No real
BOE/network access, no OpenAI. Structurally proves the module cannot reach
OpenAI (no import) and is never scheduled (not in Celery beat)."""

from __future__ import annotations

import os
from dataclasses import fields
from datetime import date

import pytest
from sqlalchemy import select

from app.celery_app import celery
from app.config import settings
from app.database import SyncSessionLocal
from app.models.historico import HistoricoBackfillRun, HistoricoDoc
from app.tasks import historico_backfill as backfill_module

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL_SYNC"), reason="requires ephemeral PostgreSQL")

DIA1, DIA2, DIA3 = date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)

SUMARIOS = {
    DIA1: [{
        "identificador": "BOE-2026-BF-1", "fecha_publicacion": DIA1,
        "titulo": "Expediente sancionador contra ACME LOGISTICA SL", "seccion_codigo": "3",
    }],
    DIA2: [{
        "identificador": "BOE-2026-BF-2", "fecha_publicacion": DIA2,
        "titulo": "Convenio de colaboración con una universidad", "seccion_codigo": "3",
    }],
    DIA3: [{
        "identificador": "BOE-2026-BF-3", "fecha_publicacion": DIA3,
        "titulo": "Providencia de apremio contra JOSE MARIA GARCIA", "seccion_codigo": "3",
    }],
}
TEXTOS = {
    "BOE-2026-BF-1": "Sancionada ACME LOGISTICA SL con CIF B12345674 por infracción grave.",
    "BOE-2026-BF-2": "Se aprueba un convenio de colaboración entre administraciones.",
    "BOE-2026-BF-3": "Providencia de apremio contra JOSE MARIA GARCIA con DNI 12345678Z.",
}


def _deps(*, fetch_sumario=None, sleep=None):
    return backfill_module.BackfillDependencies(
        fetch_sumario=fetch_sumario or (lambda d: SUMARIOS.get(d, [])),
        flatten_sumario=lambda payload, d: payload,
        fetch_text=lambda doc: (TEXTOS.get(doc["identificador"], ""), "xml", None),
        sleep=sleep or (lambda _s: None),
    )


def _habilitar(monkeypatch):
    monkeypatch.setattr(settings, "historico_backfill_enabled", True)
    monkeypatch.setattr(settings, "historico_backfill_max_dias_por_lote", 5)
    monkeypatch.setattr(settings, "historico_backfill_max_docs_por_lote", 200)


@pytest.mark.integration
def test_backfill_desactivado_no_toca_la_base(monkeypatch, clean_database):
    monkeypatch.setattr(settings, "historico_backfill_enabled", False)
    token = backfill_module.token_confirmacion(DIA1, DIA3, 5, 200)
    with pytest.raises(backfill_module.BackfillNoPermitido):
        backfill_module.run_backfill(DIA1, DIA3, confirmacion=token, dependencies=_deps())

    session = SyncSessionLocal()
    try:
        assert session.execute(select(HistoricoDoc)).scalars().all() == []
        assert session.execute(select(HistoricoBackfillRun)).scalars().all() == []
    finally:
        session.close()


@pytest.mark.integration
def test_token_de_confirmacion_incorrecto_es_rechazado(monkeypatch, clean_database):
    _habilitar(monkeypatch)
    with pytest.raises(backfill_module.BackfillNoPermitido):
        backfill_module.run_backfill(DIA1, DIA3, confirmacion="token-erroneo", dependencies=_deps())
    session = SyncSessionLocal()
    try:
        assert session.execute(select(HistoricoDoc)).scalars().all() == []
    finally:
        session.close()


@pytest.mark.integration
def test_backfill_indexa_y_es_idempotente_por_boe_id(monkeypatch, clean_database):
    _habilitar(monkeypatch)
    token = backfill_module.token_confirmacion(DIA1, DIA3, 5, 200)

    primero = backfill_module.run_backfill(DIA1, DIA3, confirmacion=token, dependencies=_deps())
    assert primero["status"] == "completado"
    assert primero["docs_indexados_total"] == 2  # BF-2's "convenio" title is not a sanction candidate

    segundo = backfill_module.run_backfill(DIA1, DIA3, confirmacion=token, dependencies=_deps())
    assert segundo["skipped"] is True
    assert segundo["reason"] == "already_completed"

    session = SyncSessionLocal()
    try:
        docs = session.execute(select(HistoricoDoc)).scalars().all()
        assert len(docs) == 2
        acme = session.execute(select(HistoricoDoc).where(HistoricoDoc.boe_id == "BOE-2026-BF-1")).scalar_one()
        assert "B12345674" in acme.identificadores
        assert acme.tsv is not None
        garcia = session.execute(select(HistoricoDoc).where(HistoricoDoc.boe_id == "BOE-2026-BF-3")).scalar_one()
        assert "12345678Z" in garcia.identificadores
        assert "JOSE MARIA GARCIA" in garcia.nombres_norm
    finally:
        session.close()


@pytest.mark.integration
def test_backfill_respeta_max_dias_y_es_reanudable(monkeypatch, clean_database):
    _habilitar(monkeypatch)
    token = backfill_module.token_confirmacion(DIA1, DIA3, 5, 200)

    primero = backfill_module.run_backfill(
        DIA1, DIA3, confirmacion=token, max_dias=1, dependencies=_deps()
    )
    assert primero["status"] == "pausado"
    assert primero["reanudable"] is True
    assert primero["dias_procesados_esta_ejecucion"] == 1

    session = SyncSessionLocal()
    try:
        run = session.execute(select(HistoricoBackfillRun)).scalar_one()
        assert run.status == "pausado"
        assert run.cursor_fecha == date(2026, 8, 2)  # walked back from DIA3
        assert run.dias_procesados == 1
    finally:
        session.close()

    # Resume: same range/token, no max_dias limit this time -> finishes.
    segundo = backfill_module.run_backfill(DIA1, DIA3, confirmacion=token, dependencies=_deps())
    assert segundo["status"] == "completado"
    assert segundo["dias_procesados_esta_ejecucion"] == 2  # only the remaining 2 days, not re-doing DIA3

    session = SyncSessionLocal()
    try:
        docs = session.execute(select(HistoricoDoc)).scalars().all()
        assert len(docs) == 2  # still just the 2 real candidates, no duplicates from resume
    finally:
        session.close()


@pytest.mark.integration
def test_backfill_reanuda_tras_fallo_de_un_dia(monkeypatch, clean_database):
    _habilitar(monkeypatch)
    token = backfill_module.token_confirmacion(DIA1, DIA3, 5, 200)

    intentos = {"n": 0}

    def fetch_con_fallo(d):
        if d == DIA2:
            intentos["n"] += 1
            if intentos["n"] == 1:
                raise RuntimeError("fallo simulado de red")
        return SUMARIOS.get(d, [])

    resultado = backfill_module.run_backfill(
        DIA1, DIA3, confirmacion=token, dependencies=_deps(fetch_sumario=fetch_con_fallo)
    )
    # The failing day still counts as processed (errors are recorded, not fatal).
    assert resultado["status"] == "completado"
    session = SyncSessionLocal()
    try:
        run = session.execute(select(HistoricoBackfillRun)).scalar_one()
        assert run.errores == 1
        docs = session.execute(select(HistoricoDoc)).scalars().all()
        assert len(docs) == 2  # DIA1 and DIA3 still indexed despite DIA2's failure
    finally:
        session.close()


@pytest.mark.integration
def test_backfill_respeta_max_documentos(monkeypatch, clean_database):
    _habilitar(monkeypatch)
    token = backfill_module.token_confirmacion(DIA1, DIA3, 5, 200)
    resultado = backfill_module.run_backfill(
        DIA1, DIA3, confirmacion=token, max_documentos=1, dependencies=_deps()
    )
    assert resultado["docs_indexados_esta_ejecucion"] <= 1


def test_plan_backfill_no_toca_red_ni_bd(monkeypatch):
    plan = backfill_module.plan_backfill(DIA1, DIA3)
    assert plan["dias"] == 3
    assert plan["token"] == backfill_module.token_confirmacion(
        DIA1, DIA3, settings.historico_backfill_max_dias_por_lote, settings.historico_backfill_max_docs_por_lote
    )
    assert "sin coste monetario" in plan["aviso"].lower()


def test_backfill_no_puede_llamar_a_openai_estructuralmente():
    """The absence of an extractor import is itself the guarantee — checked
    via the AST's actual import nodes, not a raw substring search (which
    would also match this module's own docstring explaining the guarantee)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(backfill_module))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    assert "app.services.extractor" not in imported_names
    assert not any(name.startswith("app.services.extractor") for name in imported_names)
    assert "extractor" not in {f.name for f in fields(backfill_module.BackfillDependencies)}


def test_backfill_no_esta_en_el_beat_schedule():
    assert set(celery.conf.beat_schedule.keys()) == {"scrape-boe-morning", "scrape-boe-evening"}
    for entry in celery.conf.beat_schedule.values():
        assert "backfill" not in entry["task"]
