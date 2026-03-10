export interface Sancionado {
  id: number;
  boe_document_id: number;
  nombre: string | null;
  tipo_persona: string | null;
  identificador: string | null;
  tipo_identificador: string | null;
  direccion: string | null;
  telefono: string | null;
  email: string | null;
  matricula_coche: string | null;
  importe_multa_eur: number | null;
  tipo_infraccion: string | null;
  razon_sancion: string | null;
  expediente: string | null;
  estado_publicacion: string | null;
  plazo_notificacion: string | null;
  plazo_alegaciones: string | null;
  plazo_recurso: string | null;
  base_legal: string | null;
  organismo_emisor: string | null;
  dominio_material: string | null;
  created_at: string;
  boe_id: string | null;
  fecha_publicacion: string | null;
  titulo_documento: string | null;
  url_html: string | null;
  url_documento: string | null;
  seguimientos?: Seguimiento[];
}

export interface Seguimiento {
  id: number;
  sancionado_id: number;
  nota: string | null;
  estado: string;
  created_at: string;
}

export interface Notificacion {
  id: number;
  tipo: string;
  titulo: string;
  mensaje: string | null;
  leida: boolean;
  sancionado_id: number | null;
  created_at: string;
}

export interface ScrapingRun {
  id: number;
  fecha_boe: string;
  status: string;
  total_docs: number | null;
  candidates: number | null;
  extracted: number | null;
  errors: number | null;
  error_log: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface DashboardStats {
  total_documentos: number;
  total_sancionados: number;
  documentos_hoy: number;
  sancionados_hoy: number;
  sancionados_semana: number;
  notificaciones_sin_leer: number;
  ultimo_scraping: {
    fecha: string | null;
    status: string | null;
    extracted: number | null;
    finished_at: string | null;
  };
  top_organismos: { nombre: string; total: number }[];
  infracciones_por_tipo: { tipo: string; total: number }[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}
