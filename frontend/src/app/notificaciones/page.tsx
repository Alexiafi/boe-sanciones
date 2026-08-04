"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Notificacion, PaginatedResponse } from "@/lib/types";
import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner } from "@/components/ui";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/lib/formatters";

export default function NotificacionesPage() {
  const [data, setData] = useState<PaginatedResponse<Notificacion> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [page, setPage] = useState(1);
  const [soloNoLeidas, setSoloNoLeidas] = useState(false);
  const [soloClientes, setSoloClientes] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const params: Record<string, string> = { page: page.toString(), page_size: "20" };
      if (soloNoLeidas) params.solo_no_leidas = "true";
      if (soloClientes) params.solo_clientes = "true";
      const res = await api.notificaciones.list(params);
      setData(res as unknown as PaginatedResponse<Notificacion>);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [page, soloNoLeidas, soloClientes]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const markAllRead = async () => {
    try {
      await api.notificaciones.markAllRead();
      fetchData();
    } catch {
      // surfaced implicitly: the list simply won't refresh, next manual
      // action or reload will retry.
    }
  };

  const markRead = async (ids: number[]) => {
    try {
      await api.notificaciones.markRead(ids);
      fetchData();
    } catch {
      // see markAllRead
    }
  };

  return (
    <div>
      <PageHeader
        title="Notificaciones"
        description="Alertas de nuevas sanciones detectadas."
        actions={
          <>
            <label className="flex items-center gap-2 text-sm text-on-surface-variant">
              <input
                type="checkbox"
                checked={soloNoLeidas}
                onChange={(event) => {
                  setSoloNoLeidas(event.target.checked);
                  setPage(1);
                }}
              />
              Solo no leídas
            </label>
            <label className="flex items-center gap-2 text-sm text-on-surface-variant">
              <input
                type="checkbox"
                checked={soloClientes}
                onChange={(event) => {
                  setSoloClientes(event.target.checked);
                  setPage(1);
                }}
              />
              Solo mis clientes
            </label>
            <Button variant="secondary" size="sm" onClick={markAllRead}>
              Marcar todas como leídas
            </Button>
          </>
        }
      />

      <Card className="p-0 overflow-hidden">
        {loading && <Spinner />}
        {!loading && error && (
          <div className="p-6">
            <ErrorState onRetry={fetchData} />
          </div>
        )}
        {!loading && !error && (!data || data.items.length === 0) && (
          <div className="p-6">
            <EmptyState title="No hay notificaciones." />
          </div>
        )}
        {!loading && !error && data && data.items.length > 0 && (
          <div>
            {data.items.map((n) => (
              <div
                key={n.id}
                className={cn(
                  "flex items-start gap-4 px-4 py-4 transition-colors hover:bg-surface-container-low",
                  n.leida ? "opacity-60" : "bg-secondary-container/20"
                )}
              >
                <div className={cn("mt-2 h-2 w-2 shrink-0 rounded-full", n.leida ? "bg-outline-variant" : "bg-primary")} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium text-on-surface">{n.titulo}</p>
                    <span className="shrink-0 text-xs text-on-surface-variant">{formatDateTime(n.created_at)}</span>
                  </div>
                  {n.mensaje && <p className="mt-1 truncate text-sm text-on-surface-variant">{n.mensaje}</p>}
                  <div className="mt-2 flex items-center gap-3">
                    {n.cliente_id && (
                      <Link href={`/clientes/${n.cliente_id}`} className="text-xs font-medium text-primary hover:underline">
                        Ver cliente
                      </Link>
                    )}
                    {n.sancionado_id && (
                      <Link href={`/sanciones/${n.sancionado_id}`} className="text-xs font-medium text-primary hover:underline">
                        Ver sanción
                      </Link>
                    )}
                    {!n.leida && (
                      <button onClick={() => markRead([n.id])} className="text-xs text-on-surface-variant hover:text-on-surface">
                        Marcar como leída
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && !error && data && data.total > 0 && (
          <div className="flex items-center justify-between border-t border-outline-variant/15 px-4 py-3">
            <p className="text-xs text-on-surface-variant">
              {data.total} notificaciones · Página {data.page}
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
                Anterior
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setPage((p) => p + 1)} disabled={data.items.length < 20}>
                Siguiente
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
