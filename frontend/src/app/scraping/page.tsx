"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BackfillPlan, BackfillRun, ExtraccionBatch, ModoExtraccion, ScrapingRun } from "@/lib/types";
import Link from "next/link";
import {
  Button,
  Card,
  CardTitle,
  Chip,
  ConfirmDialog,
  EmptyState,
  EstadoChip,
  Field,
  Input,
  Notice,
  PageHeader,
  Select,
  Spinner,
} from "@/components/ui";
import { formatDateTime } from "@/lib/formatters";

function scrapingStatusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "failed") return "danger" as const;
  if (status === "running") return "info" as const;
  return "neutral" as const;
}

function batchStatusTone(status: ExtraccionBatch["status"]) {
  if (status === "completado") return "success" as const;
  if (status === "fallido" || status === "expirado" || status === "cancelado") return "danger" as const;
  if (status === "enviado" || status === "en_progreso") return "info" as const;
  return "neutral" as const;
}

const BATCH_STATUS_LABEL: Record<ExtraccionBatch["status"], string> = {
  preparando: "Preparando",
  enviado: "Enviado a OpenAI",
  en_progreso: "En proceso",
  completado: "Completado",
  fallido: "Fallido",
  expirado: "Expirado",
  cancelado: "Cancelado",
};

const FASES: Record<string, string> = {
  iniciando: "Iniciando",
  descargando_boe: "Descargando documentos del BOE",
  descargando_teu: "Descargando avisos del TEU",
  extrayendo: "Extrayendo datos con OpenAI",
  encolando_batch: "Preparando el envío por lotes",
  alertas: "Buscando alertas de clientes",
};

function ProgresoRun({ run }: { run: ScrapingRun }) {
  if (run.status !== "running" || !run.fase) return null;
  const total = run.progreso_total ?? 0;
  const actual = run.progreso_actual ?? 0;
  const porcentaje = total > 0 ? Math.min(100, Math.round((actual / total) * 100)) : null;
  return (
    <div className="mt-2 min-w-48">
      <p className="text-xs text-on-surface-variant">
        {FASES[run.fase] ?? run.fase}
        {total > 0 ? ` · ${actual.toLocaleString("es-ES")}/${total.toLocaleString("es-ES")}` : ""}
      </p>
      {porcentaje !== null && (
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-container-high">
          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${porcentaje}%` }} />
        </div>
      )}
    </div>
  );
}

function providerLabel(run: ScrapingRun) {
  if (!run.extraction_requested) return "Sin OpenAI";
  return run.extraction_provider === "openai_batch" ? "OpenAI · batch" : "OpenAI · tiempo real";
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function ScrapingPage() {
  const [runs, setRuns] = useState<ScrapingRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [fecha, setFecha] = useState(todayIso);
  const [triggering, setTriggering] = useState(false);
  const [triggerResult, setTriggerResult] = useState<string | null>(null);
  const [permitirExtraccionPago, setPermitirExtraccionPago] = useState(false);
  const [modoExtraccion, setModoExtraccion] = useState<ModoExtraccion | "">("");
  const [gaps, setGaps] = useState<string[]>([]);
  const [pendientesCatchUp, setPendientesCatchUp] = useState<string[]>([]);
  const [catchUpNotice, setCatchUpNotice] = useState<string | null>(null);
  const [batches, setBatches] = useState<ExtraccionBatch[]>([]);
  const [batchNotice, setBatchNotice] = useState<string | null>(null);
  const [reindexPendientes, setReindexPendientes] = useState<number | null>(null);
  const [reindexNotice, setReindexNotice] = useState<string | null>(null);

  const [backfillDesde, setBackfillDesde] = useState(() => daysAgoIso(30));
  const [backfillHasta, setBackfillHasta] = useState(todayIso);
  const [plan, setPlan] = useState<BackfillPlan | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [launchNotice, setLaunchNotice] = useState<string | null>(null);
  const [backfillRuns, setBackfillRuns] = useState<BackfillRun[]>([]);

  const fetchRuns = useCallback(async () => {
    try {
      const data = await api.scraping.runs();
      setRuns(data as unknown as ScrapingRun[]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchBackfillRuns = useCallback(async () => {
    try {
      setBackfillRuns((await api.historico.backfillRuns()) as unknown as BackfillRun[]);
    } catch {
      setBackfillRuns([]);
    }
  }, []);

  const fetchBatches = useCallback(async () => {
    try {
      setBatches(await api.scraping.batches());
    } catch {
      setBatches([]);
    }
  }, []);

  const fetchGaps = useCallback(async () => {
    try {
      const result = await api.scraping.gaps();
      setGaps(result.gaps);
      setPendientesCatchUp(result.pendientes_catch_up ?? []);
    } catch {
      setGaps([]);
      setPendientesCatchUp([]);
    }
  }, []);

  const fetchReindexPendientes = useCallback(async () => {
    try {
      setReindexPendientes((await api.historico.reindexarPendientes()).pendientes);
    } catch {
      setReindexPendientes(null);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
    fetchBackfillRuns();
    fetchBatches();
    fetchGaps();
    fetchReindexPendientes();
    const interval = setInterval(() => {
      fetchRuns();
      fetchBackfillRuns();
      fetchBatches();
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchRuns, fetchBackfillRuns, fetchBatches, fetchGaps, fetchReindexPendientes]);

  const lanzarCatchUp = async () => {
    setCatchUpNotice(null);
    try {
      await api.scraping.catchUp();
      setCatchUpNotice("Revisión encolada: se procesarán las fechas recientes sin ejecución completada.");
      setTimeout(() => {
        fetchRuns();
        fetchGaps();
      }, 4000);
    } catch (error) {
      setCatchUpNotice(`Error: ${error}`);
    }
  };

  const comprobarBatches = async () => {
    setBatchNotice(null);
    try {
      await api.scraping.comprobarBatches();
      setBatchNotice("Comprobación encolada; los resultados se aplican en cuanto OpenAI termine.");
      setTimeout(fetchBatches, 4000);
    } catch (error) {
      setBatchNotice(`Error: ${error}`);
    }
  };

  const lanzarReindex = async () => {
    setReindexNotice(null);
    try {
      await api.historico.reindexar();
      setReindexNotice("Reindexado encolado (gratis, sin OpenAI). Tarda unos minutos según el volumen.");
      setTimeout(fetchReindexPendientes, 8000);
    } catch (error) {
      setReindexNotice(`Error: ${error}`);
    }
  };

  const handleTrigger = async (event: React.FormEvent) => {
    event.preventDefault();
    setTriggering(true);
    setTriggerResult(null);
    try {
      const res = await api.scraping.trigger(fecha, {
        permitir_extraccion_pago: permitirExtraccionPago,
        modo_extraccion: permitirExtraccionPago && modoExtraccion ? modoExtraccion : null,
      });
      const modo = (res as Record<string, string | null>).modo_extraccion;
      setTriggerResult(
        `Tarea encolada (ID: ${(res as Record<string, string>).task_id}). Se procesará en segundo plano` +
          (modo ? ` con extracción OpenAI en modo ${modo === "batch" ? "batch" : "tiempo real"}.` : " sin extracción OpenAI.")
      );
      setTimeout(fetchRuns, 3000);
    } catch (error) {
      setTriggerResult(`Error: ${error}`);
    } finally {
      setTriggering(false);
    }
  };

  const previsualizarBackfill = async () => {
    setPlanLoading(true);
    setPlanError(null);
    setPlan(null);
    try {
      const result = (await api.historico.planBackfill(backfillDesde, backfillHasta)) as unknown as BackfillPlan;
      setPlan(result);
    } catch (error) {
      setPlanError(`No se pudo previsualizar: ${error}`);
    } finally {
      setPlanLoading(false);
    }
  };

  const lanzarBackfill = async () => {
    if (!plan) return;
    setLaunching(true);
    setLaunchNotice(null);
    try {
      const res = await api.historico.lanzarBackfill({
        fecha_desde: plan.fecha_desde, fecha_hasta: plan.fecha_hasta,
        confirmar: true, confirmacion: plan.token,
      });
      setLaunchNotice(`Backfill encolado (ID: ${(res as Record<string, string>).task_id}). El progreso aparece abajo.`);
      setConfirmOpen(false);
      setPlan(null);
      setTimeout(fetchBackfillRuns, 3000);
    } catch (error) {
      setLaunchNotice(`No se pudo lanzar el backfill: ${error}`);
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div>
      <PageHeader title="Operación" description="Gestiona la captación diaria del BOE, los lotes OpenAI y el backfill histórico bajo demanda." />

      <Notice tone="info" className="mb-6">
        La captación diaria se ejecuta sola cada hora (07:30–21:30) y al arrancar el software; si el BOE aún no ha publicado,
        vuelve a intentarlo en la siguiente hora. Si la extracción OpenAI está activa en{" "}
        <Link href="/configuracion" className="font-medium underline">Configuración</Link>, las sanciones del día aparecen sin
        pulsar nada. Lo de abajo es para forzar una fecha concreta o revisar qué ha pasado.
      </Notice>

      <Card className="mb-6">
        <CardTitle>Ejecutar scraping manual</CardTitle>
        <form onSubmit={handleTrigger} className="mt-4 flex flex-wrap items-end gap-4">
          <Field label="Fecha del BOE">
            <Input type="date" value={fecha} onChange={(event) => setFecha(event.target.value)} />
          </Field>
          {permitirExtraccionPago && (
            <Field label="Modo OpenAI">
              <Select value={modoExtraccion} onChange={(event) => setModoExtraccion(event.target.value as ModoExtraccion | "")}>
                <option value="">Según configuración</option>
                <option value="tiempo_real">Tiempo real</option>
                <option value="batch">Batch (más barato, resultados en horas)</option>
              </Select>
            </Field>
          )}
          <Button type="submit" disabled={triggering}>
            {triggering ? "Encolando…" : "Ejecutar"}
          </Button>
        </form>
        <label className="mt-4 flex items-start gap-2 text-sm text-on-surface-variant">
          <input type="checkbox" checked={permitirExtraccionPago} onChange={(event) => setPermitirExtraccionPago(event.target.checked)} className="mt-1" />
          <span>Permitir extracción OpenAI para esta ejecución manual. Genera coste (acotado por el tope de documentos de Configuración). Útil para volver a extraer un día que se captó sin OpenAI.</span>
        </label>
        {triggerResult && (
          <Notice tone={triggerResult.startsWith("Error") ? "danger" : "success"} className="mt-3">
            {triggerResult}
          </Notice>
        )}
      </Card>

      <Card className="mb-6">
        <CardTitle>Huecos detectados</CardTitle>
        <p className="mt-1 text-sm text-on-surface-variant">
          Fechas sin una ejecución diaria completada en los últimos 30 días (los domingos no hay BOE). Las de la última
          semana se reintentan solas tres veces al día; también puedes forzarlo ahora.
        </p>
        <p className="mt-3 text-sm text-on-surface">{gaps.length ? gaps.join(", ") : "No hay huecos en los últimos 30 días."}</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="secondary" onClick={lanzarCatchUp} disabled={pendientesCatchUp.length === 0}>
            Ponerse al día ({pendientesCatchUp.length} {pendientesCatchUp.length === 1 ? "fecha" : "fechas"})
          </Button>
          {catchUpNotice && <span className="text-xs text-on-surface-variant">{catchUpNotice}</span>}
        </div>
      </Card>

      <Card className="p-0 overflow-hidden mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-outline-variant/15 px-6 py-4">
          <div>
            <CardTitle>Lotes OpenAI (Batch API)</CardTitle>
            <p className="mt-1 text-xs text-on-surface-variant">
              Se comprueban solos cada 5 minutos; al completarse, las sanciones aparecen en el panel como en tiempo real.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {batchNotice && <span className="text-xs text-on-surface-variant">{batchNotice}</span>}
            <Button size="sm" variant="secondary" onClick={comprobarBatches} disabled={!batches.some((b) => b.status === "enviado" || b.status === "en_progreso")}>
              Comprobar ahora
            </Button>
          </div>
        </div>
        {batches.length === 0 ? (
          <div className="p-6">
            <EmptyState title="No se ha enviado ningún lote todavía." description="Se crean cuando la extracción está en modo batch (Configuración)." />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-container-low">
                <tr>
                  {["Lote", "Tipo", "Estado", "Docs", "OK", "Errores", "Sanciones", "Enviado", "Finalizado"].map((title) => (
                    <th key={title} scope="col" className="px-4 py-3 text-left font-medium text-on-surface-variant">
                      {title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id} className="hover:bg-surface-container-low">
                    <td className="px-4 py-2.5 font-medium text-on-surface">#{b.id}</td>
                    <td className="px-4 py-2.5 text-on-surface-variant">{b.tipo === "diario" ? "Diario" : "Histórico cliente"}</td>
                    <td className="px-4 py-2.5">
                      <Chip label={BATCH_STATUS_LABEL[b.status]} tone={batchStatusTone(b.status)} />
                      {b.error_log && <p className="mt-1 max-w-xs truncate text-xs text-error" title={b.error_log}>{b.error_log}</p>}
                    </td>
                    <td className="px-4 py-2.5 text-on-surface-variant">{b.total_items}</td>
                    <td className="px-4 py-2.5 text-on-surface-variant">{b.completados}</td>
                    <td className="px-4 py-2.5 text-on-surface-variant">{b.errores ? <span className="text-error">{b.errores}</span> : b.errores}</td>
                    <td className="px-4 py-2.5 font-medium text-on-surface">{b.sancionados_creados}</td>
                    <td className="px-4 py-2.5 text-xs text-on-surface-variant">{formatDateTime(b.enviado_at)}</td>
                    <td className="px-4 py-2.5 text-xs text-on-surface-variant">{formatDateTime(b.finalizado_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="p-0 overflow-hidden mb-6">
        <div className="border-b border-outline-variant/15 px-6 py-4">
          <CardTitle>Historial de ejecuciones diarias</CardTitle>
        </div>
        {loading && <Spinner />}
        {!loading && runs.length === 0 && (
          <div className="p-6">
            <EmptyState title="No hay ejecuciones registradas." />
          </div>
        )}
        {!loading && runs.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-container-low">
                <tr>
                  {["Fecha BOE", "Estado", "OpenAI", "Docs", "Candidatos", "Extraídos", "Errores", "Inicio", "Fin"].map((title) => (
                    <th key={title} scope="col" className="px-4 py-3 text-left font-medium text-on-surface-variant">
                      {title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="hover:bg-surface-container-low">
                    <td className="px-4 py-2.5 font-medium text-on-surface">{r.fecha_boe}</td>
                    <td className="px-4 py-2.5">
                      <Chip label={r.status} tone={scrapingStatusTone(r.status)} />
                      <ProgresoRun run={r} />
                      {r.status === "completed" && r.error_log && (
                        <p className="mt-1 max-w-xs text-xs text-on-surface-variant" title={r.error_log}>{r.error_log}</p>
                      )}
                      {r.status === "failed" && r.error_log && (
                        <p className="mt-1 max-w-xs truncate text-xs text-error" title={r.error_log}>{r.error_log}</p>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-on-surface-variant">{providerLabel(r)}</td>
                    <td className="px-4 py-2.5 text-on-surface-variant">{r.total_docs ?? "-"}</td>
                    <td className="px-4 py-2.5 text-on-surface-variant">{r.candidates ?? "-"}</td>
                    <td className="px-4 py-2.5 font-medium text-on-surface">{r.extracted ?? "-"}</td>
                    <td className="px-4 py-2.5 text-on-surface-variant">
                      {r.errors ? <span className="text-error">{r.errors}</span> : (r.errors ?? "-")}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-on-surface-variant">{formatDateTime(r.started_at)}</td>
                    <td className="px-4 py-2.5 text-xs text-on-surface-variant">{formatDateTime(r.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="mb-6">
        <CardTitle>Reindexar documentos ya descargados</CardTitle>
        <p className="mt-1 text-sm text-on-surface-variant">
          Añade al índice histórico (el que usa «Consulta DNI/CIF») los documentos que la captación diaria ya descargó
          antes de que existiera el índice. Gratis: sin red y sin OpenAI. Se ejecuta solo al arrancar el software.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="secondary" onClick={lanzarReindex} disabled={reindexPendientes === 0}>
            Reindexar ahora{reindexPendientes !== null ? ` (${reindexPendientes} pendientes)` : ""}
          </Button>
          {reindexNotice && <span className="text-xs text-on-surface-variant">{reindexNotice}</span>}
        </div>
      </Card>

      <Card className="mb-6">
        <CardTitle>Backfill histórico (manual, acotado)</CardTitle>
        <p className="mt-1 text-sm text-on-surface-variant">
          Indexa documentos antiguos del BOE en el histórico, sin OpenAI y sin coste monetario. Nunca se ejecuta automáticamente:
          requiere previsualizar el rango y volumen y confirmarlo explícitamente.
        </p>
        <div className="mt-4 flex flex-wrap items-end gap-4">
          <Field label="Desde">
            <Input type="date" value={backfillDesde} onChange={(event) => { setBackfillDesde(event.target.value); setPlan(null); }} />
          </Field>
          <Field label="Hasta">
            <Input type="date" value={backfillHasta} onChange={(event) => { setBackfillHasta(event.target.value); setPlan(null); }} />
          </Field>
          <Button variant="secondary" onClick={previsualizarBackfill} disabled={planLoading}>
            {planLoading ? "Calculando…" : "Previsualizar rango"}
          </Button>
        </div>

        {planError && (
          <Notice tone="danger" className="mt-4">
            {planError}
          </Notice>
        )}

        {plan && (
          <div className="mt-4 rounded-lg bg-surface-container-low p-4 text-sm">
            <p className="text-on-surface">
              <strong>{plan.dias}</strong> días · hasta <strong>{plan.documentos_estimados}</strong> documentos estimados ·{" "}
              <strong>{plan.ejecuciones_estimadas}</strong> ejecuciones (máx. {plan.max_dias_por_ejecucion} días / {plan.max_documentos_por_ejecucion} docs cada una)
            </p>
            <p className="mt-2 text-xs text-on-surface-variant">{plan.aviso}</p>
            <div className="mt-3">
              <Button size="sm" onClick={() => setConfirmOpen(true)}>
                Confirmar y lanzar
              </Button>
            </div>
          </div>
        )}

        {launchNotice && (
          <Notice tone={launchNotice.startsWith("No se pudo") ? "danger" : "success"} className="mt-4">
            {launchNotice}
          </Notice>
        )}

        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="Confirmar backfill histórico"
          description={plan ? `${plan.dias} días, hasta ${plan.documentos_estimados} documentos. Sin OpenAI, sin coste monetario.` : undefined}
          confirmLabel={launching ? "Lanzando…" : "Lanzar backfill"}
          onConfirm={lanzarBackfill}
          confirmDisabled={launching}
        >
          {plan && <p className="text-sm text-on-surface-variant">{plan.aviso}</p>}
        </ConfirmDialog>

        <div className="mt-6">
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">Progreso (reanudable)</p>
          {backfillRuns.length === 0 ? (
            <EmptyState title="No hay backfills lanzados todavía." />
          ) : (
            <div className="space-y-2">
              {backfillRuns.map((run) => (
                <div key={run.id} className="flex items-center justify-between rounded-lg bg-surface-container-low p-3 text-sm">
                  <div>
                    <p className="text-on-surface">
                      {run.fecha_desde} → {run.fecha_hasta}
                    </p>
                    <p className="text-xs text-on-surface-variant">
                      {run.dias_procesados}/{run.dias_totales} días · {run.docs_indexados} documentos indexados
                      {run.cursor_fecha && run.status === "pausado" && ` · cursor en ${run.cursor_fecha}`}
                    </p>
                  </div>
                  <EstadoChip dominio="backfill_status" valor={run.status} />
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
