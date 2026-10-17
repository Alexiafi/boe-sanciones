import type {
  AgendaItem,
  AgendaResumen,
  ConfiguracionResponse,
  ConfiguracionRuntime,
  ExtraccionBatch,
  ModoExtraccion,
  Sancionado,
} from "@/lib/types";

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
    let message = `API error: ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      const detail = body?.detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail) && detail[0]?.msg) {
        message = detail.map((item: { msg: string }) => item.msg).join(". ");
      }
    } catch {
      /* keep the generic status message */
    }
    throw new Error(message);
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
    create: (data: Record<string, unknown>) =>
      fetchAPI<Record<string, unknown>>("/api/sanciones", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    get: (id: number) => fetchAPI<Record<string, unknown>>(`/api/sanciones/${id}`),
    update: (
      id: number,
      data: {
        estado_oportunidad?: string;
        nombre?: string | null;
        identificador?: string | null;
        tipo_identificador?: string | null;
        direccion?: string | null;
        localidad?: string | null;
        provincia?: string | null;
        codigo_postal?: string | null;
        telefono?: string | null;
        email?: string | null;
        web?: string | null;
        linkedin_url?: string | null;
        telefono_secundario?: string | null;
        facebook_url?: string | null;
        instagram_url?: string | null;
        twitter_url?: string | null;
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
      fetchAPI<{ task_id: string; status: string; estado_oportunidad: Sancionado["estado_oportunidad"] }>(`/api/sanciones/${id}/enriquecer`, { method: "POST" }),
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
    delete: (id: number) =>
      fetchAPI<{ deleted: boolean; sanciones_liberadas: number }>(`/api/clientes/${id}?confirmar=true`, {
        method: "DELETE",
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
    updateAccion: (
      clienteId: number,
      accionId: number,
      data: { estado?: string; notas?: string | null; tipo?: string; titulo?: string; fecha_programada?: string | null }
    ) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${clienteId}/acciones/${accionId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    buscarHistorico: (id: number, incluirTeu: boolean) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/historico/buscar`, {
        method: "POST",
        body: JSON.stringify({ incluir_teu: incluirTeu }),
      }),
    listHistorico: (id: number) => fetchAPI<Record<string, unknown>[]>(`/api/clientes/${id}/historico`),
    extraerHistorico: (id: number, resultadoIds: number[], permitirExtraccionPago: boolean) =>
      fetchAPI<{ task_id: string; status: string }>(`/api/clientes/${id}/historico/extraer`, {
        method: "POST",
        body: JSON.stringify({
          resultado_ids: resultadoIds, confirmar: true, permitir_extraccion_pago: permitirExtraccionPago,
        }),
      }),
    validarDocumento: (id: number, tipo: "contrato" | "factura") =>
      fetchAPI<{ listo: boolean; faltantes: { campo: string; mensaje: string }[] }>(
        `/api/clientes/${id}/documentos/validar?tipo=${tipo}`
      ),
    listDocumentos: (id: number) => fetchAPI<Record<string, unknown>[]>(`/api/clientes/${id}/documentos`),
    crearContrato: (
      id: number,
      precio: number,
      servicio: string,
      formaPago: string,
      fechaInicio?: string
    ) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/contrato`, {
        method: "POST",
        body: JSON.stringify({
          precio,
          servicio,
          forma_pago: formaPago,
          fecha_inicio: fechaInicio || null,
        }),
      }),
    crearFactura: (id: number, cuantia: number, concepto: string) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/factura`, {
        method: "POST",
        body: JSON.stringify({ cuantia, concepto }),
      }),
    listVinculos: (id: number) => fetchAPI<Record<string, unknown>[]>(`/api/clientes/${id}/vinculos`),
    addVinculo: (
      id: number,
      data: {
        cliente_vinculado_id?: number | null;
        rol: string;
        nombre?: string | null;
        tipo_persona?: string | null;
        identificador?: string | null;
        tipo_identificador?: string | null;
        telefono?: string | null;
        email?: string | null;
        notas?: string | null;
      }
    ) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/vinculos`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    updateVinculo: (id: number, vinculoId: number, data: Record<string, unknown>) =>
      fetchAPI<Record<string, unknown>>(`/api/clientes/${id}/vinculos/${vinculoId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteVinculo: (id: number, vinculoId: number) =>
      fetchAPI<{ deleted: boolean }>(`/api/clientes/${id}/vinculos/${vinculoId}`, {
        method: "DELETE",
      }),
    convertirVinculo: (id: number, vinculoId: number) =>
      fetchAPI<{ cliente: Record<string, unknown>; vinculo: Record<string, unknown>; created: boolean }>(
        `/api/clientes/${id}/vinculos/${vinculoId}/convertir`,
        { method: "POST" }
      ),
    radarAlertas: () =>
      fetchAPI<Record<string, number>>("/api/clientes/alertas/radar", { method: "POST" }),
  },

  agenda: {
    list: (params: Record<string, string> = {}) => {
      const qs = new URLSearchParams(params).toString();
      return fetchAPI<AgendaItem[]>(`/api/agenda${qs ? `?${qs}` : ""}`);
    },
    resumen: () => fetchAPI<AgendaResumen>("/api/agenda/resumen"),
  },

  historico: {
    list: (params: Record<string, string>) => {
      const qs = new URLSearchParams(params).toString();
      return fetchAPI<Record<string, unknown>>(`/api/historico?${qs}`);
    },
    archivoUrl: (id: number) => `${API_BASE}/api/historico/${id}/archivo`,
    cobertura: () => fetchAPI<Record<string, unknown>>("/api/historico/cobertura"),
    consulta: (data: { cif?: string; dni?: string; matricula?: string; nombre?: string; incluir_teu?: boolean }) =>
      fetchAPI<Record<string, unknown>>("/api/historico/consulta", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    planBackfill: (fechaDesde: string, fechaHasta: string) =>
      fetchAPI<Record<string, unknown>>("/api/historico/backfill/plan", {
        method: "POST",
        body: JSON.stringify({ fecha_desde: fechaDesde, fecha_hasta: fechaHasta }),
      }),
    lanzarBackfill: (data: {
      fecha_desde: string; fecha_hasta: string; confirmar: boolean; confirmacion: string;
      max_dias?: number; max_documentos?: number;
    }) =>
      fetchAPI<Record<string, unknown>>("/api/historico/backfill", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    backfillRuns: () => fetchAPI<Record<string, unknown>[]>("/api/historico/backfill/runs"),
    reindexarPendientes: () => fetchAPI<{ pendientes: number }>("/api/historico/reindexar/pendientes"),
    reindexar: () => fetchAPI<{ task_id: string; status: string }>("/api/historico/reindexar", { method: "POST" }),
  },

  documentos: {
    archivoUrl: (id: number) => `${API_BASE}/api/documentos/${id}/archivo`,
  },

  documentosComerciales: {
    enviar: (id: number, emailDestino: string | null, mensaje?: string) =>
      fetchAPI<Record<string, unknown>>(`/api/documentos-comerciales/${id}/enviar`, {
        method: "POST",
        body: JSON.stringify({ email_destino: emailDestino, confirmar: true, mensaje }),
      }),
    pdfUrl: (id: number) => `${API_BASE}/api/documentos-comerciales/${id}/pdf`,
    plantillas: () => fetchAPI<Record<string, unknown>[]>("/api/documentos-comerciales/plantillas"),
    actualizarPlantilla: (id: number, contenidoHtml: string, nombre?: string) =>
      fetchAPI<Record<string, unknown>>(`/api/documentos-comerciales/plantillas/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ contenido_html: contenidoHtml, nombre }),
      }),
  },

  notificaciones: {
    list: (params: Record<string, string>) => {
      const qs = new URLSearchParams(params).toString();
      return fetchAPI<Record<string, unknown>>(`/api/notificaciones?${qs}`);
    },
    unreadCount: () => fetchAPI<{ count: number; count_clientes: number }>("/api/notificaciones/unread-count"),
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
    trigger: (
      fecha: string,
      options?: { force?: boolean; permitir_extraccion_pago?: boolean; modo_extraccion?: ModoExtraccion | null }
    ) =>
      fetchAPI<Record<string, unknown>>("/api/scraping/trigger", {
        method: "POST",
        body: JSON.stringify({ fecha, ...options }),
      }),
    catchUp: () => fetchAPI<{ task_id: string; status: string }>("/api/scraping/catch-up", { method: "POST" }),
    runs: () => fetchAPI<Record<string, unknown>[]>("/api/scraping/runs"),
    batches: () => fetchAPI<ExtraccionBatch[]>("/api/scraping/batches"),
    comprobarBatches: () =>
      fetchAPI<{ task_id: string; status: string }>("/api/scraping/batches/comprobar", { method: "POST" }),
    status: (taskId: string) =>
      fetchAPI<Record<string, unknown>>(`/api/scraping/status/${taskId}`),
    gaps: (days = 30) =>
      fetchAPI<{ desde: string; hasta: string; days: number; gaps: string[]; pendientes_catch_up: string[]; note: string }>(
        `/api/scraping/gaps?days=${days}`
      ),
  },

  configuracion: {
    get: () => fetchAPI<ConfiguracionResponse>("/api/configuracion"),
    update: (data: Partial<ConfiguracionRuntime>) =>
      fetchAPI<ConfiguracionResponse>("/api/configuracion", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
};
