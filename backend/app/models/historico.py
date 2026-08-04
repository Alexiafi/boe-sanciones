"""Historical index (up to 4 years) and per-client search results.

``HistoricoDoc`` is a lightweight, regex-only index (no LLM) built either by
the manual backfill task (``app/tasks/historico_backfill.py``) or, at zero
marginal cost, by the daily pipeline (``app/tasks/scraping.py``) reusing text
it already downloaded. ``HistoricoResultado`` records a client <-> document
match produced by ``app/services/historico/busqueda.py``.

``HistoricoBackfillRun`` tracks backfill progress and is intentionally a
separate table from ``ScrapingRun``: ``ScrapingRun`` rows are keyed by a
single ``fecha_boe`` and both ``run_scraping`` (skip-if-completed) and
``GET /api/scraping/gaps`` treat a completed row for a date as "that date is
covered". A backfill spans a range with a moving cursor, not a single date;
reusing ``ScrapingRun`` for it would make the daily pipeline silently skip
real ingestion for whatever date a backfill run happened to be dated.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HistoricoDoc(Base):
    """One BOE/TEU document indexed for historical search.

    No structured extraction happens here — ``identificadores``/``matriculas``/
    ``nombres`` come from ``services/historico/patterns.py`` regexes, which is
    what keeps indexing free of LLM cost. ``nombres_norm`` is pre-normalised in
    Python (accents stripped, uppercased) so the generated ``tsv`` column can
    use the built-in ``simple`` text search configuration instead of requiring
    the ``unaccent`` extension (which can need superuser privileges to install).
    """

    __tablename__ = "historico_docs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    boe_id: Mapped[str] = mapped_column(String(50), nullable=False)
    fuente: Mapped[str] = mapped_column(String(20), nullable=False)
    fecha_publicacion: Mapped[date] = mapped_column(Date, nullable=False)
    seccion_codigo: Mapped[Optional[str]] = mapped_column(String(10))
    departamento_nombre: Mapped[Optional[str]] = mapped_column(String(500))
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    url_html: Mapped[Optional[str]] = mapped_column(Text)
    url_xml: Mapped[Optional[str]] = mapped_column(Text)
    url_pdf: Mapped[Optional[str]] = mapped_column(Text)
    texto_plano: Mapped[Optional[str]] = mapped_column(Text)
    extracto: Mapped[Optional[str]] = mapped_column(Text)
    hash_texto: Mapped[Optional[str]] = mapped_column(String(64))

    identificadores: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    matriculas: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    nombres: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    digitos_parciales: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    nombres_norm: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Generated (never a trigger, never application-maintained): PostgreSQL
    # guarantees it can never drift from nombres_norm. to_tsvector(regconfig,
    # text) with a literal config is IMMUTABLE (the 1-arg form is only STABLE),
    # which is what makes it legal in a generated column.
    tsv: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(nombres_norm, ''))", persisted=True),
    )

    familia_sancionadora: Mapped[Optional[str]] = mapped_column(String(50))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    origen_indexado: Mapped[str] = mapped_column(String(20), nullable=False, default="backfill")
    indexer_version: Mapped[str] = mapped_column(String(20), nullable=False, default="regex-1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    resultados: Mapped[list["HistoricoResultado"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("boe_id", name="uq_historico_docs_boe_id"),
        CheckConstraint("fuente IN ('boe', 'teu')", name="ck_historico_docs_fuente"),
        CheckConstraint(
            "origen_indexado IN ('backfill', 'diario', 'teu_publico')",
            name="ck_historico_docs_origen",
        ),
        Index("ix_historico_docs_fecha_publicacion", "fecha_publicacion"),
        Index("ix_historico_docs_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_historico_docs_identificadores",
            "identificadores",
            postgresql_using="gin",
            postgresql_ops={"identificadores": "jsonb_path_ops"},
        ),
        Index(
            "ix_historico_docs_matriculas",
            "matriculas",
            postgresql_using="gin",
            postgresql_ops={"matriculas": "jsonb_path_ops"},
        ),
    )


class HistoricoResultado(Base):
    """A client <-> historical-document match.

    ``UNIQUE (cliente_id, historico_doc_id)`` is what makes re-running a
    client's history search idempotent: the same search never duplicates
    rows, and the upsert in ``services/historico/busqueda.py`` never
    downgrades a stronger match or clobbers ``extraido``/``datos_extraidos``.
    """

    __tablename__ = "historico_resultados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False)
    historico_doc_id: Mapped[int] = mapped_column(
        ForeignKey("historico_docs.id", ondelete="CASCADE"), nullable=False
    )
    # Which vínculo (administrador/conductor/filial…) this match belongs to.
    # Null means it matched the client's own identifiers/name. ON DELETE SET
    # NULL: removing a vínculo must not delete previously found matches.
    vinculo_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("vinculos_cliente.id", ondelete="SET NULL"), nullable=True
    )
    score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    via_match: Mapped[str] = mapped_column(String(24), nullable=False)
    detalle_match: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="nuevo")
    extraido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    datos_extraidos: Mapped[Optional[dict]] = mapped_column(JSONB)
    extraido_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    extractor_version: Mapped[Optional[str]] = mapped_column(String(200))
    extraccion_error: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cliente: Mapped["Cliente"] = relationship(back_populates="historico_resultados")  # noqa: F821
    documento: Mapped["HistoricoDoc"] = relationship(back_populates="resultados")

    __table_args__ = (
        UniqueConstraint("cliente_id", "historico_doc_id", name="uq_historico_resultados_cliente_doc"),
        CheckConstraint(
            "via_match IN ('cif', 'dni', 'matricula', 'nombre', 'nombre_dni_parcial', 'teu_publico')",
            name="ck_historico_resultados_via_match",
        ),
        CheckConstraint(
            "estado IN ('nuevo', 'confirmado', 'descartado')",
            name="ck_historico_resultados_estado",
        ),
        Index("ix_historico_resultados_cliente_id", "cliente_id"),
    )


class HistoricoBackfillRun(Base):
    """Progress tracker for a manual, resumable historical backfill batch.

    ``cursor_fecha`` walks backwards from ``fecha_hasta`` to ``fecha_desde``
    (newest history first — that is the part most likely to matter to a new
    client). A commit happens once per processed day, in the same transaction
    that advances the cursor, so an interruption never loses or re-does more
    than the in-flight day. ``UNIQUE (fecha_desde, fecha_hasta)`` is both the
    anti-duplicate guard and the resume handle: launching the same range again
    simply continues from ``cursor_fecha``.
    """

    __tablename__ = "historico_backfill_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha_desde: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    cursor_fecha: Mapped[Optional[date]] = mapped_column(Date)
    ultima_fecha_completada: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    dias_totales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dias_procesados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_vistos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_candidatos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    docs_indexados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errores: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_log: Mapped[Optional[str]] = mapped_column(Text)
    confirmacion_token: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("fecha_desde", "fecha_hasta", name="uq_historico_backfill_runs_rango"),
        CheckConstraint(
            "status IN ('pendiente', 'en_curso', 'pausado', 'completado', 'error')",
            name="ck_historico_backfill_runs_status",
        ),
        CheckConstraint("fecha_desde <= fecha_hasta", name="ck_historico_backfill_runs_rango_valido"),
    )
