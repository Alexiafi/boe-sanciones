"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardStats } from "@/lib/types";

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-3xl font-bold mt-1">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.dashboard
      .stats()
      .then((data) => setStats(data as unknown as DashboardStats))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="bg-card rounded-xl border border-border p-8 text-center">
        <p className="text-muted-foreground">
          No se pudo conectar con el servidor. Asegurate de que el backend esta corriendo.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground mt-1">Resumen general del sistema de sanciones BOE</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total documentos" value={stats.total_documentos} />
        <StatCard label="Total sancionados" value={stats.total_sancionados} />
        <StatCard
          label="Sancionados hoy"
          value={stats.sancionados_hoy}
          sub={`${stats.sancionados_semana} esta semana`}
        />
        <StatCard
          label="Notificaciones"
          value={stats.notificaciones_sin_leer}
          sub="sin leer"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h2 className="text-lg font-semibold mb-4">Ultimo scraping</h2>
          {stats.ultimo_scraping.fecha ? (
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Fecha BOE</span>
                <span className="font-medium">{stats.ultimo_scraping.fecha}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Estado</span>
                <span
                  className={`font-medium px-2 py-0.5 rounded-full text-xs ${
                    stats.ultimo_scraping.status === "completed"
                      ? "bg-green-100 text-green-800"
                      : stats.ultimo_scraping.status === "failed"
                        ? "bg-red-100 text-red-800"
                        : "bg-yellow-100 text-yellow-800"
                  }`}
                >
                  {stats.ultimo_scraping.status}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Extraidos</span>
                <span className="font-medium">{stats.ultimo_scraping.extracted ?? 0}</span>
              </div>
              {stats.ultimo_scraping.finished_at && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Finalizado</span>
                  <span className="font-medium">
                    {new Date(stats.ultimo_scraping.finished_at).toLocaleString("es-ES")}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Aun no se ha ejecutado ningun scraping.</p>
          )}
        </div>

        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h2 className="text-lg font-semibold mb-4">Top organismos sancionadores</h2>
          {stats.top_organismos.length > 0 ? (
            <div className="space-y-3">
              {stats.top_organismos.map((org) => (
                <div key={org.nombre} className="flex justify-between items-center">
                  <span className="text-sm truncate max-w-xs" title={org.nombre}>
                    {org.nombre}
                  </span>
                  <span className="bg-primary/10 text-primary font-semibold text-xs px-2 py-0.5 rounded-full ml-2 shrink-0">
                    {org.total}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Sin datos aun.</p>
          )}
        </div>

        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h2 className="text-lg font-semibold mb-4">Infracciones por tipo</h2>
          {stats.infracciones_por_tipo.length > 0 ? (
            <div className="space-y-3">
              {stats.infracciones_por_tipo.map((inf) => (
                <div key={inf.tipo} className="flex justify-between items-center">
                  <span className="text-sm capitalize">
                    {inf.tipo?.replace("_", " ") || "Sin tipo"}
                  </span>
                  <span
                    className={`font-semibold text-xs px-2 py-0.5 rounded-full ${
                      inf.tipo === "muy_grave"
                        ? "bg-red-100 text-red-800"
                        : inf.tipo === "grave"
                          ? "bg-orange-100 text-orange-800"
                          : "bg-yellow-100 text-yellow-800"
                    }`}
                  >
                    {inf.total}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">Sin datos aun.</p>
          )}
        </div>
      </div>
    </div>
  );
}
