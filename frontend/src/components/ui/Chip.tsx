import { cn } from "@/lib/utils";

export type ChipTone = "neutral" | "info" | "success" | "warning" | "danger" | "primary";

const toneClasses: Record<ChipTone, string> = {
  neutral: "bg-surface-container-highest text-on-surface-variant",
  info: "bg-secondary-container text-on-secondary-container",
  success: "bg-success-container text-on-success-container",
  warning: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
  danger: "bg-error-container text-on-error-container",
  primary: "bg-primary-container text-on-primary",
};

interface ChipProps {
  label: string;
  tone?: ChipTone;
  className?: string;
}

export function Chip({ label, tone = "neutral", className }: ChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium uppercase tracking-[0.05em]",
        toneClasses[tone],
        className
      )}
    >
      {label}
    </span>
  );
}

/**
 * Single source of truth for every status chip in the app — one place to
 * look up what color a given domain/value pair renders as, instead of each
 * page hand-rolling its own color map (the pre-redesign state had 7+
 * independent copies of this).
 */
type Dominio =
  | "estado_oportunidad"
  | "estado_cliente"
  | "contacto_estado"
  | "documento_estado"
  | "accion_estado"
  | "prescripcion"
  | "backfill_status";

const MAPAS: Record<Dominio, Record<string, { label: string; tone: ChipTone }>> = {
  estado_oportunidad: {
    nueva: { label: "Nueva", tone: "info" },
    revisada: { label: "Revisada", tone: "neutral" },
    contactada: { label: "Contactada", tone: "warning" },
    descartada: { label: "Descartada", tone: "danger" },
    cliente: { label: "Cliente", tone: "success" },
  },
  estado_cliente: {
    activo: { label: "Activo", tone: "success" },
    inactivo: { label: "Inactivo", tone: "neutral" },
  },
  contacto_estado: {
    pendiente: { label: "Pendiente", tone: "neutral" },
    encontrado: { label: "Encontrado", tone: "success" },
    no_encontrado: { label: "No encontrado", tone: "warning" },
    manual: { label: "Manual", tone: "info" },
  },
  documento_estado: {
    generado: { label: "Generado", tone: "neutral" },
    enviado: { label: "Enviado", tone: "success" },
    error_envio: { label: "Error de envío", tone: "danger" },
  },
  accion_estado: {
    pendiente: { label: "Pendiente", tone: "warning" },
    hecha: { label: "Hecha", tone: "success" },
    cancelada: { label: "Cancelada", tone: "neutral" },
  },
  prescripcion: {
    urgente: { label: "Urgente", tone: "danger" },
    proximo: { label: "Próximo vencimiento", tone: "warning" },
    reciente: { label: "Reciente", tone: "info" },
    archivado: { label: "Archivado", tone: "neutral" },
  },
  backfill_status: {
    pendiente: { label: "Pendiente", tone: "neutral" },
    en_curso: { label: "En curso", tone: "info" },
    pausado: { label: "Pausado", tone: "warning" },
    completado: { label: "Completado", tone: "success" },
    error: { label: "Error", tone: "danger" },
  },
};

export function EstadoChip({ dominio, valor, className }: { dominio: Dominio; valor: string | null | undefined; className?: string }) {
  if (!valor) return <Chip label="—" tone="neutral" className={className} />;
  const entry = MAPAS[dominio][valor] ?? { label: valor, tone: "neutral" as ChipTone };
  return <Chip label={entry.label} tone={entry.tone} className={className} />;
}
