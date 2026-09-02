export interface Sancionado {
  id: number;
  boe_document_id: number;
  codigo: string;
  estado_oportunidad: "nueva" | "revisada" | "contactada" | "descartada" | "cliente";
  nombre: string | null;
  tipo_persona: string | null;
  identificador: string | null;
  tipo_identificador: string | null;
  direccion: string | null;
  localidad: string | null;
  provincia: string | null;
  codigo_postal: string | null;
  telefono: string | null;
  email: string | null;
  matricula_coche: string | null;
  importe_multa_eur: number | null;
  tipo_infraccion: string | null;
  razon_sancion: string | null;
  expediente: string | null;
  estado_publicacion: string | null;
  tipo_procedimiento: string | null;
  importe_deuda_eur: number | null;
  plazo_notificacion: string | null;
  plazo_alegaciones: string | null;
  plazo_recurso: string | null;
  plazo_pago_voluntario: string | null;
  base_legal: string | null;
  organismo_emisor: string | null;
  dominio_material: string | null;
  fecha_resolucion: string | null;
  observaciones: string | null;
  created_at: string;

  // Contact enrichment (session 2)
  web: string | null;
  linkedin_url: string | null;
  telefono_secundario: string | null;
  facebook_url: string | null;
  instagram_url: string | null;
  twitter_url: string | null;
  contacto_detalle: Record<string, { valor: string; fuente_url: string | null; confidence: number }> | null;
  contacto_estado: "pendiente" | "encontrado" | "no_encontrado" | "manual" | "sin_datos";
  contacto_fuente: string | null;
  contacto_url: string | null;
  contacto_confidence: number | null;
  contacto_actualizado_at: string | null;
  cliente_id: number | null;

  boe_id: string | null;
  fecha_publicacion: string | null;
  titulo_documento: string | null;
  url_html: string | null;
  url_documento: string | null;
  tiene_copia_local: boolean;
  seguimientos?: Seguimiento[];
}

export interface EnriquecimientoIntento {
  id: number;
  sancionado_id: number;
  proveedor: string;
  consulta: string | null;
  resultado: "encontrado" | "no_encontrado" | "error" | "omitido" | "sin_datos";
  url_origen: string | null;
  confidence: number | null;
  evidencia: string | null;
  coste_estimado_eur: number | null;
  duracion_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface Cliente {
  id: number;
  codigo: string;
  nombre_razon_social: string;
  tipo_persona: string | null;
  cif_nif: string | null;
  dni_nie: string | null;
  matriculas: string[];
  persona_contacto: string | null;
  telefono: string | null;
  email: string | null;
  direccion_fiscal: string | null;
  localidad: string | null;
  provincia: string | null;
  codigo_postal: string | null;
  web: string | null;
  sector: string | null;
  estado_cliente: "activo" | "inactivo";
  fecha_contrato: string | null;
  precio_contrato: number | null;
  sancion_origen_id: number;
  created_at: string;
  deuda_pendiente_eur: number;
}

export interface SancionVinculada {
  id: number;
  codigo: string;
  fecha_publicacion: string | null;
  tipo_infraccion: string | null;
  importe_multa_eur: number | null;
  importe_deuda_eur: number | null;
  url_documento: string | null;
  vinculo_id: number | null;
  titular: string | null;
}

export interface VinculoCliente {
  id: number;
  cliente_id: number;
  cliente_vinculado_id: number | null;
  rol: string;
  nombre: string | null;
  tipo_persona: "fisica" | "juridica" | null;
  identificador: string | null;
  tipo_identificador: string | null;
  telefono: string | null;
  email: string | null;
  notas: string | null;
  created_at: string;
}

export interface NotaCliente {
  id: number;
  cliente_id: number;
  texto: string;
  autor: string | null;
  created_at: string;
}

export interface ActividadCliente {
  id: number;
  cliente_id: number;
  tipo: "llamada" | "email" | "pago" | "nota" | "conversion" | "sistema";
  titulo: string;
  detalle: string | null;
  datos: Record<string, unknown> | null;
  created_at: string;
}

export interface AccionAgendada {
  id: number;
  cliente_id: number;
  tipo: "llamada" | "email" | "tarea";
  titulo: string;
  fecha_programada: string | null;
  estado: "pendiente" | "hecha" | "cancelada";
  notas: string | null;
  created_at: string;
}

export interface ClienteDetail extends Cliente {
  sanciones: SancionVinculada[];
  notas: NotaCliente[];
  actividades: ActividadCliente[];
  acciones: AccionAgendada[];
  vinculos: VinculoCliente[];
}

export interface HistoricoResultado {
  id: number;
  cliente_id: number;
  historico_doc_id: number;
  vinculo_id: number | null;
  score: number;
  via_match: "cif" | "dni" | "matricula" | "nombre" | "nombre_dni_parcial" | "teu_publico";
  estado: "nuevo" | "confirmado" | "descartado";
  extraido: boolean;
  datos_extraidos: Record<string, unknown> | null;
  created_at: string;
  boe_id: string | null;
  fuente: "boe" | "teu" | null;
  fecha_publicacion: string | null;
  titulo: string | null;
  url_pdf: string | null;
  url_html: string | null;
  url_xml: string | null;
  fuera_de_ventana_teu: boolean;
  titular: string | null;
}

export interface CoberturaTeu {
  ventana_publica_desde: string;
  consulta_en_vivo: boolean;
  motivo_sin_consulta: string | null;
}

export interface ConsultaItem {
  historico_doc_id: number;
  boe_id: string;
  fuente: "boe" | "teu";
  fecha_publicacion: string;
  titulo: string;
  via_match: string;
  score: number;
  url_pdf: string | null;
  url_html: string | null;
  url_xml: string | null;
  fuera_de_ventana_teu: boolean;
}

export interface HistoricoDocItem {
  id: number;
  boe_id: string;
  fuente: "boe" | "teu";
  fecha_publicacion: string;
  titulo: string;
  departamento_nombre: string | null;
  url_pdf: string | null;
  url_html: string | null;
  url_xml: string | null;
  origen_indexado: string;
  fuera_de_ventana_teu: boolean;
  tiene_copia_local: boolean;
}

export interface HistoricoCobertura {
  boe_desde: string | null;
  boe_hasta: string | null;
  boe_dias_indexados: number;
  teu_desde: string | null;
  teu_hasta: string | null;
  teu_dias_indexados: number;
  total_documentos: number;
  ventana_publica_teu_desde: string;
}

export interface BackfillPlan {
  fecha_desde: string;
  fecha_hasta: string;
  dias: number;
  documentos_estimados: number;
  candidatos_estimados: number;
  max_dias_por_ejecucion: number;
  max_documentos_por_ejecucion: number;
  ejecuciones_estimadas: number;
  token: string;
  aviso: string;
}

export interface BackfillRun {
  id: number;
  fecha_desde: string;
  fecha_hasta: string;
  cursor_fecha: string | null;
  ultima_fecha_completada: string | null;
  status: "pendiente" | "en_curso" | "pausado" | "completado" | "error";
  dias_totales: number;
  dias_procesados: number;
  docs_vistos: number;
  docs_candidatos: number;
  docs_indexados: number;
  errores: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface DocumentoComercial {
  id: number;
  cliente_id: number;
  tipo: "contrato" | "factura";
  serie: string | null;
  numero: string | null;
  estado: "generado" | "enviado" | "error_envio";
  email_destino: string | null;
  enviado_at: string | null;
  created_at: string;
  datos: Record<string, unknown> | null;
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
  cliente_id: number | null;
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
  extraction_requested: boolean;
  extraction_provider: string | null;
  extraction_limit: number | null;
  extraction_attempts: number;
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
  alertas_clientes_sin_leer: number;
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
