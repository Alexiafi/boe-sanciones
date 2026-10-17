"use client";

import { useState } from "react";
import type { AccionAgendada } from "@/lib/types";
import { Button, Chip, EstadoChip, Input } from "@/components/ui";
import { formatDateTime, isoADateTimeLocal } from "@/lib/formatters";

export function AccionItem({
  accion,
  onEstado,
  onReprogramar,
}: {
  accion: AccionAgendada;
  onEstado: (accion: AccionAgendada, estado: "hecha" | "cancelada") => void;
  onReprogramar: (accion: AccionAgendada, fechaLocal: string) => void;
}) {
  const [editando, setEditando] = useState(false);
  const [fecha, setFecha] = useState(isoADateTimeLocal(accion.fecha_programada));
  const vencida = accion.estado === "pendiente" && !!accion.fecha_programada && new Date(accion.fecha_programada) < new Date();
  return (
    <div className="rounded-lg bg-surface-container-low p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-on-surface">{accion.titulo}</span>
        <EstadoChip dominio="accion_estado" valor={accion.estado} />
      </div>
      <p className="mt-1 text-xs text-on-surface-variant">
        {accion.tipo} · {accion.fecha_programada ? formatDateTime(accion.fecha_programada) : "sin fecha"}
        {vencida && <Chip label="Vencida" tone="danger" className="ml-2" />}
      </p>
      {accion.notas && <p className="mt-1 text-xs text-on-surface">{accion.notas}</p>}
      {accion.estado === "pendiente" && (
        <div className="mt-2 space-y-2">
          <div className="flex flex-wrap gap-3">
            <button onClick={() => onEstado(accion, "hecha")} className="text-xs text-primary hover:underline">
              Marcar hecha
            </button>
            <button onClick={() => setEditando((v) => !v)} className="text-xs text-primary hover:underline">
              Cambiar fecha
            </button>
            <button onClick={() => onEstado(accion, "cancelada")} className="text-xs text-on-surface-variant hover:underline">
              Cancelar
            </button>
          </div>
          {editando && (
            <div className="flex items-center gap-2">
              <Input type="datetime-local" value={fecha} onChange={(event) => setFecha(event.target.value)} />
              <Button
                size="sm"
                onClick={() => {
                  onReprogramar(accion, fecha);
                  setEditando(false);
                }}
              >
                Guardar
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
