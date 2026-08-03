"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { DashboardStats } from "@/lib/types";
import { Card, CardTitle, Chip, EmptyState, ErrorState, LinkButton, PageHeader, Spinner, StatCard } from "@/components/ui";
import { formatDateTime } from "@/lib/formatters";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    api.dashboard
      .stats()
      .then((data) => setStats(data as unknown as DashboardStats))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // Fetch-on-mount + a reusable retry handler (ErrorState's onRetry below)
    // is the intended shape here, not an accidental render loop: `load`
    // itself guards re-entrancy via loading/error state, so this doesn't
    // cascade.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="Inicio"
        description="Acceso directo al panel de multas, el histórico y la cartera de clientes."
        actions={
          <>
            <LinkButton href="/sanciones">Panel de Multas</LinkButton>
            <LinkButton href="/historial" variant="ghost">Historial</LinkButton>
            <LinkButton href="/clientes" variant="ghost">Clientes</LinkButton>
          </>
        }
      />

      {loading && <Spinner />}
      {!loading && error && <ErrorState onRetry={load} />}
      {!loading && !error && stats && (
        <>
          <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total documentos" value={stats.total_documentos} />
            <StatCard label="Total sancionados" value={stats.total_sancionados} />
            <StatCard label="Sancionados hoy" value={stats.sancionados_hoy} sub={`${stats.sancionados_semana} esta semana`} />
            <StatCard label="Notificaciones" value={stats.notificaciones_sin_leer} sub="sin leer" />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card>
              <CardTitle>Último scraping</CardTitle>
              {stats.ultimo_scraping.fecha ? (
                <div className="mt-4 space-y-2.5 text-sm">
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">Fecha BOE</span>
                    <span className="font-medium text-on-surface">{stats.ultimo_scraping.fecha}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-on-surface-variant">Estado</span>
                    <Chip
                      label={stats.ultimo_scraping.status ?? "—"}
                      tone={
                        stats.ultimo_scraping.status === "completed"
                          ? "success"
                          : stats.ultimo_scraping.status === "failed"
                            ? "danger"
                            : "warning"
                      }
                    />
                  </div>
                  <div className="flex justify-between">
                    <span className="text-on-surface-variant">Extraídos</span>
                    <span className="font-medium text-on-surface">{stats.ultimo_scraping.extracted ?? 0}</span>
                  </div>
                  {stats.ultimo_scraping.finished_at && (
                    <div className="flex justify-between">
                      <span className="text-on-surface-variant">Finalizado</span>
                      <span className="font-medium text-on-surface">{formatDateTime(stats.ultimo_scraping.finished_at)}</span>
                    </div>
                  )}
                </div>
              ) : (
                <EmptyState title="Aún no se ha ejecutado ningún scraping." />
              )}
            </Card>

            <Card>
              <CardTitle>Top organismos sancionadores</CardTitle>
              {stats.top_organismos.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {stats.top_organismos.map((org) => (
                    <div key={org.nombre} className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm text-on-surface" title={org.nombre}>
                        {org.nombre}
                      </span>
                      <Chip label={String(org.total)} tone="primary" />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Sin datos aún." />
              )}
            </Card>

            <Card>
              <CardTitle>Infracciones por tipo</CardTitle>
              {stats.infracciones_por_tipo.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {stats.infracciones_por_tipo.map((inf) => (
                    <div key={inf.tipo} className="flex items-center justify-between">
                      <span className="text-sm capitalize text-on-surface">{inf.tipo?.replace("_", " ") || "Sin tipo"}</span>
                      <Chip
                        label={String(inf.total)}
                        tone={inf.tipo === "muy_grave" ? "danger" : inf.tipo === "grave" ? "warning" : "neutral"}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Sin datos aún." />
              )}
            </Card>

            <Card>
              <CardTitle>Accesos rápidos</CardTitle>
              <div className="mt-4 flex flex-col gap-2">
                <Link href="/consulta" className="text-sm text-primary hover:underline">
                  Consulta por DNI/CIF →
                </Link>
                <Link href="/scraping" className="text-sm text-primary hover:underline">
                  Lanzar operación / backfill →
                </Link>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
