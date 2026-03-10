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
    addSeguimiento: (id: number, data: { nota?: string; estado: string }) =>
      fetchAPI<Record<string, unknown>>(`/api/sanciones/${id}/seguimientos`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    getSeguimientos: (id: number) =>
      fetchAPI<Record<string, unknown>[]>(`/api/sanciones/${id}/seguimientos`),
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
    trigger: (fecha: string) =>
      fetchAPI<Record<string, unknown>>("/api/scraping/trigger", {
        method: "POST",
        body: JSON.stringify({ fecha }),
      }),
    runs: () => fetchAPI<Record<string, unknown>[]>("/api/scraping/runs"),
    status: (taskId: string) =>
      fetchAPI<Record<string, unknown>>(`/api/scraping/status/${taskId}`),
  },
};
