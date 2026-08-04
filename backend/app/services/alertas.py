"""Free daily radar over the historical index.

Unlike ``services/vinculos.asignar_sancion_a_cliente`` (which only fires when
today's OpenAI extraction ran), this reuses ``services/historico/busqueda.py``
against ``historico_docs`` — which is indexed for free every day regardless of
``OPENAI_EXTRACTION_ENABLED`` (see ``tasks/scraping._process_candidate`` →
``upsert_from_doc_data``). It is the only detection path that still works with
paid extraction turned off.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cliente import Cliente, VinculoCliente
from app.models.historico import HistoricoResultado
from app.models.notificacion import Notificacion
from app.services.historico.busqueda import buscar_historico

# Only exact identifier matches (via "cif"/"dni"/"matricula", score 0.90+)
# trigger an alert — a name-only match is too noisy for an unattended radar
# that runs across every active client; those still show up in the client's
# own "Buscar histórico" results for manual review.
UMBRAL_SCORE_ALERTA = 0.90


def _notificar_hallazgo(db: Session, cliente: Cliente, resultado: HistoricoResultado) -> None:
    doc = resultado.documento
    titular = cliente.nombre_razon_social
    rol: str | None = None
    if resultado.vinculo_id is not None:
        vinculo = db.get(VinculoCliente, resultado.vinculo_id)
        if vinculo is not None:
            titular = vinculo.nombre or titular
            rol = vinculo.rol

    titulo = f"Nueva sanción de cliente: {titular}"
    if rol:
        titulo += f" ({rol})"
    mensaje = f"{doc.titulo} · {doc.fecha_publicacion.isoformat()} · {doc.fuente.upper()} · vía {resultado.via_match}"

    db.add(Notificacion(
        tipo="nueva_sancion_cliente", titulo=titulo, mensaje=mensaje, leida=False,
        sancionado_id=None, cliente_id=cliente.id,
    ))


def ejecutar_radar_clientes(db: Session) -> dict[str, int]:
    """Search every active client's (and their vínculos') history and alert
    on brand-new, high-confidence matches. Idempotent: ``buscar_historico``
    never duplicates ``HistoricoResultado`` rows, and this only ever alerts
    once per row — the first time it's created."""
    clientes = db.execute(select(Cliente).where(Cliente.estado_cliente == "activo")).scalars().all()
    stats = {"clientes_revisados": len(clientes), "alertas_creadas": 0}

    for cliente in clientes:
        resultado = buscar_historico(db, cliente, incluir_teu=False)
        nuevos_ids = set(resultado["nuevos"])
        if not nuevos_ids:
            continue
        for historico_resultado in resultado["resultados"]:
            if historico_resultado.id in nuevos_ids and float(historico_resultado.score) >= UMBRAL_SCORE_ALERTA:
                _notificar_hallazgo(db, cliente, historico_resultado)
                stats["alertas_creadas"] += 1

    db.commit()
    return stats
