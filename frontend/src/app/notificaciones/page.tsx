"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Notificacion, PaginatedResponse } from "@/lib/types";

export default function NotificacionesPage() {
  const [data, setData] = useState<PaginatedResponse<Notificacion> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [soloNoLeidas, setSoloNoLeidas] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        page: page.toString(),
        page_size: "20",
      };
      if (soloNoLeidas) params.solo_no_leidas = "true";
      const res = await api.notificaciones.list(params);
      setData(res as unknown as PaginatedResponse<Notificacion>);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [page, soloNoLeidas]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const markAllRead = async () => {
    try {
      await api.notificaciones.markAllRead();
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const markRead = async (ids: number[]) => {
    try {
      await api.notificaciones.markRead(ids);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Notificaciones</h1>
          <p className="text-muted-foreground mt-1">Alertas de nuevas sanciones detectadas</p>
        </div>
        <div className="flex gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={soloNoLeidas}
              onChange={(e) => {
                setSoloNoLeidas(e.target.checked);
                setPage(1);
              }}
              className="rounded"
            />
            Solo no leidas
          </label>
          <button
            onClick={markAllRead}
            className="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
          >
            Marcar todas como leidas
          </button>
        </div>
      </div>

      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-48">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            No hay notificaciones.
          </div>
        ) : (
          <div className="divide-y divide-border">
            {data.items.map((n) => (
              <div
                key={n.id}
                className={`p-4 flex items-start gap-4 transition-colors ${
                  n.leida ? "opacity-60" : "bg-primary/5"
                }`}
              >
                <div
                  className={`w-2 h-2 rounded-full mt-2 shrink-0 ${
                    n.leida ? "bg-muted-foreground/30" : "bg-primary"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium text-sm truncate">{n.titulo}</p>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {new Date(n.created_at).toLocaleString("es-ES")}
                    </span>
                  </div>
                  {n.mensaje && (
                    <p className="text-sm text-muted-foreground mt-1 truncate">{n.mensaje}</p>
                  )}
                  <div className="flex items-center gap-3 mt-2">
                    {n.sancionado_id && (
                      <Link
                        href={`/sanciones/${n.sancionado_id}`}
                        className="text-primary hover:underline text-xs font-medium"
                      >
                        Ver sancion
                      </Link>
                    )}
                    {!n.leida && (
                      <button
                        onClick={() => markRead([n.id])}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        Marcar como leida
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {data && data.total > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/30">
            <p className="text-xs text-muted-foreground">
              {data.total} notificaciones | Pagina {data.page}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1 text-xs border border-border rounded-md hover:bg-muted disabled:opacity-50"
              >
                Anterior
              </button>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={data.items.length < 20}
                className="px-3 py-1 text-xs border border-border rounded-md hover:bg-muted disabled:opacity-50"
              >
                Siguiente
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
