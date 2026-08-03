"""Client history search: exact JSONB match + full-text search by normalised
name, plus the optional (off-by-default) TEU public-search complement.

Search is idempotent: re-running it for the same client never duplicates
``HistoricoResultado`` rows, never downgrades a previously stronger match,
and never touches ``extraido``/``datos_extraidos``/``estado`` — a re-search
must not erase prior on-demand extraction work or the user's
confirmado/descartado decision (see ``_persistir_resultado``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.historico import HistoricoDoc, HistoricoResultado
from app.services.historico.indexado import upsert_historico_doc
from app.services.historico.patterns import (
    dni_encaja_con_mascara,
    normalizar_identificador,
    normalizar_matricula,
    normalizar_nombre,
)
from app.services.historico.teu_publico import (
    AVISO_TEU,
    EntradaTeu,
    TeuBuscador,
    fuera_de_ventana_teu,
    get_teu_buscador,
    teu_search_available,
)

__all__ = [
    "AVISO_TEU",
    "ClavesCliente",
    "buscar_historico",
    "claves_de_cliente",
    "consultar_historico",
]


@dataclass(frozen=True)
class ClavesCliente:
    identificadores: list[str]
    matriculas: list[str]
    nombre_norm: str
    dni_completo: str | None


def claves_de_cliente(cliente: Cliente) -> ClavesCliente:
    identificadores = [normalizar_identificador(v) for v in (cliente.cif_nif, cliente.dni_nie) if v]
    matriculas = [normalizar_matricula(m) for m in (cliente.matriculas or []) if m]
    nombre_norm = normalizar_nombre(cliente.nombre_razon_social)
    dni_completo = normalizar_identificador(cliente.dni_nie) if cliente.dni_nie else None
    return ClavesCliente(
        identificadores=identificadores, matriculas=matriculas, nombre_norm=nombre_norm,
        dni_completo=dni_completo,
    )


def _claves_de_consulta(
    *, cif: str | None, dni: str | None, matricula: str | None, nombre: str | None
) -> ClavesCliente:
    identificadores = [normalizar_identificador(v) for v in (cif, dni) if v]
    matriculas = [normalizar_matricula(matricula)] if matricula else []
    nombre_norm = normalizar_nombre(nombre) if nombre else ""
    dni_completo = normalizar_identificador(dni) if dni else None
    return ClavesCliente(identificadores, matriculas, nombre_norm, dni_completo)


def _mejor(acumulado: dict[int, tuple[HistoricoDoc, str, float]], doc: HistoricoDoc, via: str, score: float) -> None:
    previo = acumulado.get(doc.id)
    if previo is None or score > previo[2]:
        acumulado[doc.id] = (doc, via, score)


def _buscar_exactas(db: Session, claves: ClavesCliente) -> list[tuple[HistoricoDoc, str, float]]:
    encontrados: list[tuple[HistoricoDoc, str, float]] = []
    for idx, clave in enumerate(claves.identificadores):
        via = "cif" if idx == 0 else "dni"
        docs = db.execute(
            select(HistoricoDoc).where(HistoricoDoc.identificadores.contains([clave]))
        ).scalars().all()
        encontrados.extend((doc, via, 1.0) for doc in docs)
    for matricula in claves.matriculas:
        docs = db.execute(
            select(HistoricoDoc).where(HistoricoDoc.matriculas.contains([matricula]))
        ).scalars().all()
        encontrados.extend((doc, "matricula", 0.90) for doc in docs)
    return encontrados


def _buscar_por_nombre(db: Session, claves: ClavesCliente, *, limite: int) -> list[tuple[HistoricoDoc, str, float]]:
    if not claves.nombre_norm:
        return []

    frase = db.execute(
        text(
            "SELECT id, ts_rank(tsv, phraseto_tsquery('simple', :q)) AS rank FROM historico_docs "
            "WHERE tsv @@ phraseto_tsquery('simple', :q) ORDER BY rank DESC LIMIT :limite"
        ),
        {"q": claves.nombre_norm, "limite": limite},
    ).all()

    if frase:
        rangos = {row.id: float(row.rank) for row in frase}
        base_score = 0.60
    else:
        bolsa = db.execute(
            text(
                "SELECT id, ts_rank(tsv, plainto_tsquery('simple', :q)) AS rank FROM historico_docs "
                "WHERE tsv @@ plainto_tsquery('simple', :q) ORDER BY rank DESC LIMIT :limite"
            ),
            {"q": claves.nombre_norm, "limite": limite},
        ).all()
        rangos = {row.id: float(row.rank) for row in bolsa}
        base_score = 0.35

    if not rangos:
        return []

    docs = db.execute(select(HistoricoDoc).where(HistoricoDoc.id.in_(rangos.keys()))).scalars().all()
    resultados: list[tuple[HistoricoDoc, str, float]] = []
    for doc in docs:
        score = min(0.95, base_score + min(0.10, rangos.get(doc.id, 0.0) * 2))
        via = "nombre"
        if claves.dni_completo and any(
            dni_encaja_con_mascara(claves.dni_completo, m) for m in (doc.digitos_parciales or [])
        ):
            via, score = "nombre_dni_parcial", max(score, 0.85)
        resultados.append((doc, via, score))
    return resultados


def _materializar_entradas_teu(db: Session, entradas: list[EntradaTeu]) -> list[HistoricoDoc]:
    docs: list[HistoricoDoc] = []
    for entrada in entradas:
        if not entrada.identificador:
            continue  # defensive parse produced no stable id; skip rather than guess
        doc, _ = upsert_historico_doc(
            db,
            boe_id=entrada.identificador,
            fuente="teu",
            fecha_publicacion=entrada.fecha_publicacion,
            titulo=entrada.titulo,
            origen_indexado="teu_publico",
            departamento_nombre=entrada.departamento_nombre,
            url_pdf=entrada.url_pdf,
        )
        docs.append(doc)
    return docs


def _buscar_teu(
    db: Session, claves: ClavesCliente, *, buscador_teu: TeuBuscador | None
) -> tuple[list[tuple[HistoricoDoc, str, float]], str | None]:
    disponible, motivo = teu_search_available()
    if not disponible:
        return [], motivo
    buscador = buscador_teu or get_teu_buscador()
    if buscador is None:
        return [], "Conector TEU no disponible."
    hasta = date.today()
    desde = hasta - timedelta(days=90)
    encontrados: list[tuple[HistoricoDoc, str, float]] = []
    for clave in claves.identificadores:
        entradas = buscador.buscar_por_clave(clave, desde=desde, hasta=hasta)
        for doc in _materializar_entradas_teu(db, entradas):
            encontrados.append((doc, "teu_publico", 0.95))
    return encontrados, None


def _persistir_resultado(db: Session, cliente_id: int, doc: HistoricoDoc, via: str, score: float) -> HistoricoResultado:
    existing = db.execute(
        select(HistoricoResultado).where(
            HistoricoResultado.cliente_id == cliente_id,
            HistoricoResultado.historico_doc_id == doc.id,
        )
    ).scalar_one_or_none()
    if existing:
        vias = set((existing.detalle_match or {}).get("vias", [])) | {via}
        if float(score) > float(existing.score):
            existing.score = score
            existing.via_match = via
        existing.detalle_match = {"vias": sorted(vias)}
        return existing
    resultado = HistoricoResultado(
        cliente_id=cliente_id, historico_doc_id=doc.id, score=score, via_match=via,
        detalle_match={"vias": [via]},
    )
    db.add(resultado)
    db.flush()
    return resultado


def _cobertura_teu(desde: date | None = None, hasta: date | None = None) -> dict:
    return {
        "ventana_publica_desde": (date.today() - timedelta(days=90)).isoformat(),
        "consulta_en_vivo": teu_search_available()[0],
        "motivo_sin_consulta": teu_search_available()[1],
    }


def buscar_historico(
    db: Session, cliente: Cliente, *, incluir_teu: bool = False, limite: int = 200,
    buscador_teu: TeuBuscador | None = None,
) -> dict:
    """Search + persist. Returns {"resultados": [...], "avisos": [...]}."""
    claves = claves_de_cliente(cliente)
    acumulado: dict[int, tuple[HistoricoDoc, str, float]] = {}
    for doc, via, score in _buscar_exactas(db, claves):
        _mejor(acumulado, doc, via, score)
    for doc, via, score in _buscar_por_nombre(db, claves, limite=limite):
        _mejor(acumulado, doc, via, score)

    avisos = [AVISO_TEU]
    if incluir_teu:
        teu_hits, motivo = _buscar_teu(db, claves, buscador_teu=buscador_teu)
        if motivo:
            avisos.append(motivo)
        for doc, via, score in teu_hits:
            _mejor(acumulado, doc, via, score)

    resultados = [
        _persistir_resultado(db, cliente.id, doc, via, score)
        for doc, via, score in acumulado.values()
    ]
    db.commit()
    return {"resultados": resultados, "avisos": avisos, "cobertura_teu": _cobertura_teu()}


def consultar_historico(
    db: Session, *, cif: str | None = None, dni: str | None = None, matricula: str | None = None,
    nombre: str | None = None, incluir_teu: bool = False, limite: int = 200,
    buscador_teu: TeuBuscador | None = None,
) -> dict:
    """Read-only lookup for the internal "Consulta por DNI/CIF" screen — no
    ``cliente_id`` exists here, so no ``HistoricoResultado`` row is written.
    TEU hits, if requested and available, are still materialised into the
    shared ``historico_docs`` index (that accumulation is the point)."""
    claves = _claves_de_consulta(cif=cif, dni=dni, matricula=matricula, nombre=nombre)
    acumulado: dict[int, tuple[HistoricoDoc, str, float]] = {}
    for doc, via, score in _buscar_exactas(db, claves):
        _mejor(acumulado, doc, via, score)
    for doc, via, score in _buscar_por_nombre(db, claves, limite=limite):
        _mejor(acumulado, doc, via, score)

    avisos = [AVISO_TEU]
    if incluir_teu:
        teu_hits, motivo = _buscar_teu(db, claves, buscador_teu=buscador_teu)
        if motivo:
            avisos.append(motivo)
        for doc, via, score in teu_hits:
            _mejor(acumulado, doc, via, score)
        db.commit()

    ordenados = sorted(acumulado.values(), key=lambda item: item[2], reverse=True)[:limite]
    hoy = date.today()
    items = [
        {
            "historico_doc_id": doc.id,
            "boe_id": doc.boe_id,
            "fuente": doc.fuente,
            "fecha_publicacion": doc.fecha_publicacion.isoformat(),
            "titulo": doc.titulo,
            "via_match": via,
            "score": score,
            "url_pdf": doc.url_pdf,
            "url_html": doc.url_html,
            "url_xml": doc.url_xml,
            "fuera_de_ventana_teu": doc.fuente == "teu" and fuera_de_ventana_teu(doc.fecha_publicacion, hoy=hoy),
        }
        for doc, via, score in ordenados
    ]
    return {"resultados": items, "avisos": avisos, "cobertura_teu": _cobertura_teu()}
