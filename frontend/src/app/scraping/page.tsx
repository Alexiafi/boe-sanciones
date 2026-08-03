"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ScrapingRun } from "@/lib/types";

export default function ScrapingPage() {
  const [runs, setRuns] = useState<ScrapingRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [fecha, setFecha] = useState(() => {
    const d = new Date();
    return d.toISOString().split("T")[0];
  });
  const [triggering, setTriggering] = useState(false);
  const [triggerResult, setTriggerResult] = useState<string | null>(null);
  const [permitirExtraccionPago, setPermitirExtraccionPago] = useState(false);
  const [gaps, setGaps] = useState<string[]>([]);

  const fetchRuns = useCallback(async () => {
    try {
      const data = await api.scraping.runs();
      setRuns(data as unknown as ScrapingRun[]);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
    api.scraping.gaps().then((result) => setGaps(result.gaps)).catch(console.error);
    const interval = setInterval(fetchRuns, 10000);
    return () => clearInterval(interval);
  }, [fetchRuns]);

  const handleTrigger = async (e: React.FormEvent) => {
    e.preventDefault();
    setTriggering(true);
    setTriggerResult(null);
    try {
      const res = await api.scraping.trigger(fecha, { permitir_extraccion_pago: permitirExtraccionPago });
      setTriggerResult(
        `Tarea encolada (ID: ${(res as Record<string, string>).task_id}). Se procesara en segundo plano.`
      );
      setTimeout(fetchRuns, 3000);
    } catch (err) {
      setTriggerResult(`Error: ${err}`);
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Scraping</h1>
        <p className="text-muted-foreground mt-1">
          Gestiona la extraccion de sanciones del BOE
        </p>
      </div>

      {/* Trigger form */}
      <div className="bg-card rounded-xl border border-border p-6 shadow-sm mb-6">
        <h2 className="text-lg font-semibold mb-4">Ejecutar scraping manual</h2>
        <form onSubmit={handleTrigger} className="flex items-end gap-4">
          <div>
            <label className="block text-sm text-muted-foreground mb-1">Fecha del BOE</label>
            <input
              type="date"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
              className="px-3 py-2 border border-border rounded-lg text-sm bg-background"
            />
          </div>
          <button
            type="submit"
            disabled={triggering}
            className="bg-primary text-primary-foreground px-6 py-2 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {triggering ? "Encolando..." : "Ejecutar"}
          </button>
        </form>
        <label className="mt-4 flex items-start gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={permitirExtraccionPago} onChange={(event) => setPermitirExtraccionPago(event.target.checked)} className="mt-1" />
          <span>Permitir extracción OpenAI para esta ejecución manual. Puede generar coste y está limitada por configuración.</span>
        </label>
        {triggerResult && (
          <p className={`mt-3 text-sm ${triggerResult.startsWith("Error") ? "text-red-600" : "text-green-600"}`}>
            {triggerResult}
          </p>
        )}
      </div>

      <div className="bg-card rounded-xl border border-border p-6 shadow-sm mb-6">
        <h2 className="text-lg font-semibold">Huecos detectados</h2>
        <p className="text-sm text-muted-foreground mt-1">Fechas sin una ejecución completada; esta lista no inicia ni programa scraping.</p>
        <p className="mt-3 text-sm">{gaps.length ? gaps.join(", ") : "No hay huecos en los últimos 30 días."}</p>
      </div>

      {/* Runs history */}
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold">Historial de ejecuciones</h2>
        </div>
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        ) : runs.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            No hay ejecuciones registradas.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted border-b border-border">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Fecha BOE</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Estado</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Docs</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Candidatos</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Extraidos</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Errores</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Inicio</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">Fin</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {runs.map((r) => (
                  <tr key={r.id} className="hover:bg-muted/50 transition-colors">
                    <td className="px-4 py-3 font-medium">{r.fecha_boe}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          r.status === "completed"
                            ? "bg-green-100 text-green-800"
                            : r.status === "failed"
                              ? "bg-red-100 text-red-800"
                              : r.status === "running"
                                ? "bg-blue-100 text-blue-800"
                                : "bg-gray-100 text-gray-800"
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{r.total_docs ?? "-"}</td>
                    <td className="px-4 py-3 text-muted-foreground">{r.candidates ?? "-"}</td>
                    <td className="px-4 py-3 font-medium">{r.extracted ?? "-"}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {r.errors ? (
                        <span className="text-red-600">{r.errors}</span>
                      ) : (
                        r.errors ?? "-"
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {r.started_at ? new Date(r.started_at).toLocaleString("es-ES") : "-"}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {r.finished_at ? new Date(r.finished_at).toLocaleString("es-ES") : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
