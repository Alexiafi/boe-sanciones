"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { HistoricoResultado } from "@/lib/types";
import { Button, Card, CardTitle, Chip, EmptyState, Notice, Spinner } from "@/components/ui";
import { formatDate } from "@/lib/formatters";

const AVISO_TEU =
  "El Tablón Edictal Único (TEU) solo permite consulta pública durante 90 días desde la publicación. " +
  "Para fechas anteriores solo se muestra lo que este sistema haya acumulado por sí mismo desde su puesta en marcha; " +
  "el BOE ordinario sí cubre el histórico completo.";

export function HistoricoBlock({ clienteId }: { clienteId: number }) {
  const [resultados, setResultados] = useState<HistoricoResultado[]>([]);
  const [loading, setLoading] = useState(true);
  const [buscando, setBuscando] = useState(false);
  const [incluirTeu, setIncluirTeu] = useState(false);
  const [avisos, setAvisos] = useState<string[]>([]);
  const [seleccion, setSeleccion] = useState<Set<number>>(new Set());
  const [extraccionNotice, setExtraccionNotice] = useState<string | null>(null);
  const [extrayendo, setExtrayendo] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const items = (await api.clientes.listHistorico(clienteId)) as unknown as HistoricoResultado[];
      setResultados(items);
    } catch {
      setResultados([]);
    } finally {
      setLoading(false);
    }
  }, [clienteId]);

  useEffect(() => {
    load();
  }, [load]);

  const buscar = async () => {
    setBuscando(true);
    setAvisos([]);
    try {
      const resp = (await api.clientes.buscarHistorico(clienteId, incluirTeu)) as unknown as {
        resultados: HistoricoResultado[];
        avisos: string[];
      };
      setResultados(resp.resultados);
      setAvisos(resp.avisos);
    } catch (error) {
      setAvisos([`No se pudo buscar el histórico: ${error}`]);
    } finally {
      setBuscando(false);
    }
  };

  const toggleSeleccion = (id: number) => {
    setSeleccion((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const extraer = async () => {
    if (seleccion.size === 0) return;
    setExtrayendo(true);
    setExtraccionNotice(null);
    try {
      await api.clientes.extraerHistorico(clienteId, Array.from(seleccion), true);
      setExtraccionNotice(
        "Extracción encolada. Requiere OpenAI configurado y habilitado en el servidor; si no lo está, no se ejecutará ningún cargo. Recarga en unos segundos para ver el resultado."
      );
      setSeleccion(new Set());
    } catch (error) {
      setExtraccionNotice(`No se pudo lanzar la extracción: ${error}`);
    } finally {
      setExtrayendo(false);
    }
  };

  return (
    <Card>
      <div className="mb-4 flex items-center justify-between">
        <CardTitle>Histórico sancionador</CardTitle>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-on-surface-variant">
            <input type="checkbox" checked={incluirTeu} onChange={(event) => setIncluirTeu(event.target.checked)} />
            Incluir búsqueda pública TEU (en vivo)
          </label>
          <Button size="sm" onClick={buscar} disabled={buscando}>
            {buscando ? "Buscando…" : "Buscar histórico"}
          </Button>
        </div>
      </div>

      <Notice tone="warning" className="mb-4">
        {AVISO_TEU}
      </Notice>

      {avisos
        .filter((aviso) => aviso !== AVISO_TEU) // already shown above, unconditionally
        .map((aviso, index) => (
          <Notice key={index} tone="info" className="mb-4">
            {aviso}
          </Notice>
        ))}

      {loading && <Spinner />}
      {!loading && resultados.length === 0 && (
        <EmptyState
          title="Sin resultados de histórico todavía."
          description="Pulsa «Buscar histórico» para casar el CIF/DNI/matrícula y el nombre del cliente contra el índice acumulado."
        />
      )}
      {!loading && resultados.length > 0 && (
        <>
          <div className="space-y-2">
            {resultados.map((item) => (
              <div key={item.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <label className="flex flex-1 items-start gap-2">
                    {!item.extraido && (
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={seleccion.has(item.id)}
                        onChange={() => toggleSeleccion(item.id)}
                      />
                    )}
                    <div>
                      <p className="font-medium text-on-surface">{item.titulo || item.boe_id}</p>
                      <p className="text-xs text-on-surface-variant">
                        {formatDate(item.fecha_publicacion)} · {item.fuente?.toUpperCase()} · vía {item.via_match} · score {item.score.toFixed(2)}
                        {item.vinculo_id && item.titular && ` · ${item.titular}`}
                      </p>
                    </div>
                  </label>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    {item.vinculo_id && item.titular && <Chip label={item.titular} tone="neutral" />}
                    {item.extraido && <Chip label="Extraído" tone="success" />}
                    {item.fuera_de_ventana_teu && <span className="text-[10px] uppercase text-on-surface-variant">Solo acumulado</span>}
                    {(item.url_pdf || item.url_html) && (
                      <a
                        href={item.url_pdf || item.url_html || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-primary hover:underline"
                      >
                        Ver documento
                      </a>
                    )}
                  </div>
                </div>
                {item.extraido && item.datos_extraidos && (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-primary">Ver datos extraídos</summary>
                    <pre className="mt-1 overflow-x-auto rounded bg-surface-container-highest p-2 text-[11px]">
                      {JSON.stringify(item.datos_extraidos, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-3">
            <Button size="sm" variant="secondary" onClick={extraer} disabled={seleccion.size === 0 || extrayendo}>
              {extrayendo ? "Encolando…" : `Extraer seleccionados (${seleccion.size})`}
            </Button>
          </div>
          {extraccionNotice && (
            <Notice tone="info" className="mt-3">
              {extraccionNotice}
            </Notice>
          )}
        </>
      )}
    </Card>
  );
}
