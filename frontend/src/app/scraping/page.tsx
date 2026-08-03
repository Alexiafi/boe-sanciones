"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BackfillPlan, BackfillRun, ScrapingRun } from "@/lib/types";
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
  Spinner,
} from "@/components/ui";
import { formatDateTime } from "@/lib/formatters";

function scrapingStatusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "failed") return "danger" as const;
  if (status === "running") return "info" as const;
  return "neutral" as const;
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
  const [gaps, setGaps] = useState<string[]>([]);

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

  useEffect(() => {
    fetchRuns();
    fetchBackfillRuns();
    api.scraping.gaps().then((result) => setGaps(result.gaps)).catch(() => setGaps([]));
    const interval = setInterval(() => {
      fetchRuns();
      fetchBackfillRuns();
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchRuns, fetchBackfillRuns]);

  const handleTrigger = async (event: React.FormEvent) => {
    event.preventDefault();
    setTriggering(true);
    setTriggerResult(null);
    try {
      const res = await api.scraping.trigger(fecha, { permitir_extraccion_pago: permitirExtraccionPago });
      setTriggerResult(`Tarea encolada (ID: ${(res as Record<string, string>).task_id}). Se procesará en segundo plano.`);
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
      <PageHeader title="Operación" description="Gestiona la extracción diaria del BOE y el backfill histórico bajo demanda." />

      <Card className="mb-6">
        <CardTitle>Ejecutar scraping manual</CardTitle>
        <form onSubmit={handleTrigger} className="mt-4 flex items-end gap-4">
          <Field label="Fecha del BOE">
            <Input type="date" value={fecha} onChange={(event) => setFecha(event.target.value)} />
          </Field>
          <Button type="submit" disabled={triggering}>
            {triggering ? "Encolando…" : "Ejecutar"}
          </Button>
        </form>
        <label className="mt-4 flex items-start gap-2 text-sm text-on-surface-variant">
          <input type="checkbox" checked={permitirExtraccionPago} onChange={(event) => setPermitirExtraccionPago(event.target.checked)} className="mt-1" />
          <span>Permitir extracción OpenAI para esta ejecución manual. Puede generar coste y está limitada por configuración.</span>
        </label>
        {triggerResult && (
          <Notice tone={triggerResult.startsWith("Error") ? "danger" : "success"} className="mt-3">
            {triggerResult}
          </Notice>
        )}
      </Card>

      <Card className="mb-6">
        <CardTitle>Huecos detectados</CardTitle>
        <p className="mt-1 text-sm text-on-surface-variant">Fechas sin una ejecución diaria completada; esta lista no inicia ni programa scraping.</p>
        <p className="mt-3 text-sm text-on-surface">{gaps.length ? gaps.join(", ") : "No hay huecos en los últimos 30 días."}</p>
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
                  {["Fecha BOE", "Estado", "Docs", "Candidatos", "Extraídos", "Errores", "Inicio", "Fin"].map((title) => (
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
                    </td>
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
