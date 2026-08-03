const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  dashboard: {
    stats: () => fetchAPI<Record<string, unknown>>("/api/dashboard/stats"),
  },

  sanciones: {
    list: (params: Record<string, string>) => {
      const qs = new URLSearchParams(params).toString();
      return fetchAPI<Record<string, unknown>>(`/api/sanciones?${qs}`);
    },
    get: (id: number) => fetchAPI<Record<string, unknown>>(`/api/sanciones/${id}`),
    update: (
      id: number,
      data: {
        estado_oportunidad?: string;
        telefono?: string | null;
        email?: string | null;
        web?: string | null;
        linkedin_url?: string | null;
        telefono_secundario?: string | null;
      }
    ) =>
      fetchAPI<Record<string, unknown>>(`/api/sanciones/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    addSeguimiento: (id: number, data: { nota?: string; estado: string }) =>
      fetchAPI<Record<string, unknown>>(`/api/sanciones/${id}/seguimientos`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    getSeguimientos: (id: number) =>
      fetchAPI<Record<string, unknown>[]>(`/api/sanciones/${id}/seguimientos`),
    enrich: (id: number) =>
      fetchAPI<{ task_id: string; status: string }>(`/api/sanciones/${id}/enriquecer`, { method: "POST" }),
    enrichmentAttempts: (id: number) =>
      fetchAPI<Record<string, unknown>[]>(`/api/sanciones/${id}/enriquecimiento`),
    convertir: (id: number) =>
      fetchAPI<{ cliente: Record<string, unknown>; created: boolean }>(`/api/sanciones/${id}/convertir`, {
        method: "POST",
      }),
  },

  clientes: {
    list: (params: Record<string, string>) => {
      const qs = new URLSearchParams(params).toString();
      return fetchAPI<Record<string, unknown>>(`/api/clientes?${qs}`);
    },
    get: (id: number) => fetchAPI<Record<string, unknown>>(`/api/clientes/${id}`),
    update: (id: number, data: Record<string, unknown>) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    addNota: (id: number, data: { texto: string; autor?: string | null }) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/notas`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    addAccion: (id: number, data: { tipo: string; titulo: string; fecha_programada?: string | null; notas?: string | null }) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/acciones`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateAccion: (clienteId: number, accionId: number, data: { estado?: string; notas?: string | null }) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${clienteId}/acciones/${accionId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
  },

  notificaciones: {
    list: (params: Record<string, string>) => {
      const qs = new URLSearchParams(params).toString();
      return fetchAPI<Record<string, unknown>>(`/api/notificaciones?${qs}`);
    },
    unreadCount: () => fetchAPI<{ count: number }>("/api/notificaciones/unread-count"),
    markRead: (ids: number[]) =>
      fetchAPI<Record<string, unknown>>("/api/notificaciones/mark-read", {
        method: "POST",
        body: JSON.stringify({ ids }),
      }),
    markAllRead: () =>
      fetchAPI<Record<string, unknown>>("/api/notificaciones/mark-all-read", {
        method: "POST",
      }),
  },

  scraping: {
    trigger: (fecha: string, options?: { force?: boolean; permitir_extraccion_pago?: boolean }) =>
      fetchAPI<Record<string, unknown>>("/api/scraping/trigger", {
        method: "POST",
        body: JSON.stringify({ fecha, ...options }),
      }),
    runs: () => fetchAPI<Record<string, unknown>[]>("/api/scraping/runs"),
    status: (taskId: string) =>
      fetchAPI<Record<string, unknown>>(`/api/scraping/status/${taskId}`),
    gaps: (days = 30) =>
      fetchAPI<{ desde: string; hasta: string; days: number; gaps: string[]; note: string }>(`/api/scraping/gaps?days=${days}`),
  },
};
