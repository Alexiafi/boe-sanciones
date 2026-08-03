"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { HistoricoCobertura, HistoricoDocItem, PaginatedResponse } from "@/lib/types";
import { Card, Chip, EmptyState, ErrorState, Field, Notice, PageHeader, Pagination, Select, Spinner, StatCard } from "@/components/ui";
import { formatDate } from "@/lib/formatters";
import { prescripcionTier } from "@/lib/prescripcion";

const AVISO_TEU =
  "El Tablón Edictal Único (TEU) solo permite consulta pública durante 90 días desde la publicación. " +
  "Este archivo solo muestra, para fechas anteriores, lo que el sistema haya acumulado por sí mismo desde su puesta en marcha; " +
  "el BOE ordinario sí queda cubierto de forma indefinida. Las etiquetas de estado temporal son orientativas (antigüedad de " +
  "publicación), no un cálculo de prescripción legal.";

export default function HistorialPage() {
  const [data, setData] = useState<PaginatedResponse<HistoricoDocItem> | null>(null);
  const [cobertura, setCobertura] = useState<HistoricoCobertura | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [page, setPage] = useState(1);
  const [fuente, setFuente] = useState("");
  const [anio, setAnio] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const params: Record<string, string> = { page: String(page), page_size: "20" };
      if (fuente) params.fuente = fuente;
      if (anio) params.anio = anio;
      const [listado, coberturaRes] = await Promise.all([
        api.historico.list(params) as unknown as Promise<PaginatedResponse<HistoricoDocItem>>,
        api.historico.cobertura() as unknown as Promise<HistoricoCobertura>,
      ]);
      setData(listado);
      setCobertura(coberturaRes);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [page, fuente, anio]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div>
      <PageHeader title="Historial" description="Archivo general de sanciones incorporadas al índice histórico." />

      <Notice tone="warning" className="mb-6">
        {AVISO_TEU}
      </Notice>

      {cobertura && (
        <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatCard label="Documentos indexados" value={cobertura.total_documentos} />
          <StatCard
            label="Cobertura BOE"
            value={cobertura.boe_dias_indexados}
            sub={cobertura.boe_desde ? `días · desde ${formatDate(cobertura.boe_desde)}` : "días indexados"}
          />
          <StatCard
            label="Cobertura TEU"
            value={cobertura.teu_dias_indexados}
            sub={`días · ventana pública desde ${formatDate(cobertura.ventana_publica_teu_desde)}`}
          />
        </div>
      )}

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="Fuente">
            <Select value={fuente} onChange={(event) => { setFuente(event.target.value); setPage(1); }}>
              <option value="">Todas</option>
              <option value="boe">BOE</option>
              <option value="teu">TEU</option>
            </Select>
          </Field>
          <Field label="Año">
            <Select value={anio} onChange={(event) => { setAnio(event.target.value); setPage(1); }}>
              <option value="">Todos</option>
              {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - i).map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        {loading && <Spinner />}
        {!loading && error && (
          <div className="p-6">
            <ErrorState onRetry={fetchData} />
          </div>
        )}
        {!loading && !error && !data?.items.length && (
          <div className="p-6">
            <EmptyState title="Sin documentos en el histórico." description="Lanza un backfill acotado desde Operación o espera a la acumulación diaria." />
          </div>
        )}
        {!loading && !error && !!data?.items.length && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-container-low">
                  <tr>
                    {["Referencia", "Título", "Fecha", "Fuente", "Estado", "Documento"].map((title) => (
                      <th key={title} scope="col" className="px-4 py-3 text-left font-medium text-on-surface-variant">
                        {title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((doc) => {
                    const tier = prescripcionTier(doc.fecha_publicacion, doc.fuente);
                    return (
                      <tr key={doc.id} className="hover:bg-surface-container-low">
                        <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{doc.boe_id}</td>
                        <td className="max-w-[320px] truncate px-4 py-2.5 text-on-surface" title={doc.titulo}>
                          {doc.titulo}
                        </td>
                        <td className="px-4 py-2.5 text-on-surface-variant">{formatDate(doc.fecha_publicacion)}</td>
                        <td className="px-4 py-2.5">
                          <Chip label={doc.fuente.toUpperCase()} tone={doc.fuente === "teu" ? "primary" : "neutral"} />
                        </td>
                        <td className="px-4 py-2.5">
                          <EstadoChipPrescripcion tier={tier} />
                        </td>
                        <td className="px-4 py-2.5">
                          {doc.url_pdf || doc.url_html ? (
                            <a href={doc.url_pdf || doc.url_html || "#"} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                              Ver original
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="px-4 pb-4">
              <Pagination page={data.page} pages={data.pages} total={data.total} onChange={setPage} />
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function EstadoChipPrescripcion({ tier }: { tier: ReturnType<typeof prescripcionTier> }) {
  const labels = { urgente: "Urgente", proximo: "Próximo", reciente: "Reciente", archivado: "Archivado" } as const;
  const tones = { urgente: "danger", proximo: "warning", reciente: "info", archivado: "neutral" } as const;
  return <Chip label={labels[tier]} tone={tones[tier]} />;
}
