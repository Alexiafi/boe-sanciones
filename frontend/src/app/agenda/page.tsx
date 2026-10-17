"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { AgendaItem, AgendaResumen } from "@/lib/types";
import { Button, Card, Chip, EmptyState, ErrorState, EstadoChip, Field, PageHeader, Select, Spinner } from "@/components/ui";
import { formatDateTime } from "@/lib/formatters";

type Grupo = "vencidas" | "hoy" | "proximas" | "sin_fecha" | "otras";

const TITULOS: Record<Grupo, string> = {
  vencidas: "Vencidas",
  hoy: "Para hoy",
  proximas: "Próximas",
  sin_fecha: "Sin fecha",
  otras: "Resto",
};

function mismoDia(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function clasificar(item: AgendaItem, ahora: Date, soloPendientes: boolean): Grupo {
  if (!soloPendientes) return "otras";
  if (!item.fecha_programada) return "sin_fecha";
  const fecha = new Date(item.fecha_programada);
  if (mismoDia(fecha, ahora)) return item.vencida ? "vencidas" : "hoy";
  return fecha < ahora ? "vencidas" : "proximas";
}

export default function AgendaPage() {
  const [items, setItems] = useState<AgendaItem[] | null>(null);
  const [resumen, setResumen] = useState<AgendaResumen | null>(null);
  const [estado, setEstado] = useState("pendiente");
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [lista, contadores] = await Promise.all([api.agenda.list({ estado }), api.agenda.resumen()]);
      setItems(lista);
      setResumen(contadores);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [estado]);

  useEffect(() => {
    load();
  }, [load]);

  const marcar = async (item: AgendaItem, nuevo: "hecha" | "cancelada") => {
    try {
      await api.clientes.updateAccion(item.cliente_id, item.id, { estado: nuevo });
      await load();
    } catch {
      setError(true);
    }
  };

  const ahora = new Date();
  const soloPendientes = estado === "pendiente";
  const grupos: Grupo[] = soloPendientes ? ["vencidas", "hoy", "proximas", "sin_fecha"] : ["otras"];

  return (
    <div>
      <PageHeader
        title="Agenda"
        description="Todas las llamadas, emails y tareas que has agendado en las fichas de tus clientes, por orden de fecha."
      />

      {resumen && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Contador label="Vencidas" valor={resumen.vencidas} tono={resumen.vencidas ? "danger" : "neutral"} />
          <Contador label="Para hoy" valor={resumen.hoy} tono={resumen.hoy ? "warning" : "neutral"} />
          <Contador label="Próximas" valor={resumen.proximas} tono="info" />
          <Contador label="Sin fecha" valor={resumen.sin_fecha} tono="neutral" />
        </div>
      )}

      <Card className="mb-6">
        <div className="max-w-xs">
          <Field label="Mostrar">
            <Select value={estado} onChange={(event) => setEstado(event.target.value)}>
              <option value="pendiente">Pendientes</option>
              <option value="hecha">Hechas</option>
              <option value="cancelada">Canceladas</option>
              <option value="todas">Todas</option>
            </Select>
          </Field>
        </div>
      </Card>

      {loading && <Spinner />}
      {!loading && error && <ErrorState onRetry={load} />}
      {!loading && !error && items && items.length === 0 && (
        <Card>
          <EmptyState
            title="No hay acciones."
            description="Agenda una llamada o una tarea desde la ficha de un cliente (bloque «Agenda»)."
          />
        </Card>
      )}
      {!loading && !error && items && items.length > 0 && (
        <div className="space-y-6">
          {grupos.map((grupo) => {
            const delGrupo = items.filter((item) => clasificar(item, ahora, soloPendientes) === grupo);
            if (delGrupo.length === 0) return null;
            return (
              <Card key={grupo}>
                <h2 className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-on-surface-variant">
                  {TITULOS[grupo]} · {delGrupo.length}
                </h2>
                <div className="space-y-2">
                  {delGrupo.map((item) => (
                    <div key={item.id} className="flex flex-col gap-3 rounded-lg bg-surface-container-low p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <Chip label={item.tipo} tone="info" />
                          <span className="font-medium text-on-surface">{item.titulo}</span>
                          {item.vencida && <Chip label="Vencida" tone="danger" />}
                          {!soloPendientes && <EstadoChip dominio="accion_estado" valor={item.estado} />}
                        </div>
                        <p className="mt-1 text-xs text-on-surface-variant">
                          <Link href={`/clientes/${item.cliente_id}`} className="font-medium text-primary hover:underline">
                            {item.cliente_nombre}
                          </Link>
                          {" · "}
                          {item.fecha_programada ? formatDateTime(item.fecha_programada) : "sin fecha"}
                        </p>
                        {item.notas && <p className="mt-1 text-xs text-on-surface">{item.notas}</p>}
                      </div>
                      {item.estado === "pendiente" && (
                        <div className="flex shrink-0 gap-2">
                          <Button size="sm" onClick={() => marcar(item, "hecha")}>
                            Hecha
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => marcar(item, "cancelada")}>
                            Cancelar
                          </Button>
                          <Link
                            href={`/clientes/${item.cliente_id}`}
                            className="inline-flex items-center rounded-lg px-2 text-xs font-medium text-primary hover:underline"
                          >
                            Abrir ficha
                          </Link>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Contador({ label, valor, tono }: { label: string; valor: number; tono: "danger" | "warning" | "info" | "neutral" }) {
  return (
    <div className="rounded-2xl border border-outline-variant/55 bg-white p-5 shadow-ambient">
      <p className="text-[9px] font-bold uppercase tracking-[0.13em] text-on-surface-variant">{label}</p>
      <p className="mt-1 flex items-center gap-2 text-2xl font-extrabold tracking-[-0.04em] text-primary">
        {valor}
        {tono !== "neutral" && valor > 0 && <Chip label={tono === "danger" ? "atender" : tono === "warning" ? "hoy" : "pronto"} tone={tono} />}
      </p>
    </div>
  );
}
