"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Sancionado, Seguimiento } from "@/lib/types";

function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (!value && value !== 0) return null;
  return (
    <div className="flex justify-between py-2 border-b border-border last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-right max-w-[60%]">{value}</span>
    </div>
  );
}

const ESTADOS_SEGUIMIENTO = [
  { value: "pendiente", label: "Pendiente", color: "bg-gray-100 text-gray-800" },
  { value: "contactado", label: "Contactado", color: "bg-blue-100 text-blue-800" },
  { value: "en_gestion", label: "En gestion", color: "bg-yellow-100 text-yellow-800" },
  { value: "descartado", label: "Descartado", color: "bg-red-100 text-red-800" },
  { value: "resuelto", label: "Resuelto", color: "bg-green-100 text-green-800" },
];

export default function SancionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [sancion, setSancion] = useState<Sancionado | null>(null);
  const [seguimientos, setSeguimientos] = useState<Seguimiento[]>([]);
  const [loading, setLoading] = useState(true);
  const [nota, setNota] = useState("");
  const [estado, setEstado] = useState("pendiente");
  const [submitting, setSubmitting] = useState(false);

  const fetchSancion = useCallback(async () => {
    try {
      const data = await api.sanciones.get(parseInt(id));
      const s = data as unknown as Sancionado;
      setSancion(s);
      setSeguimientos(s.seguimientos || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchSancion();
  }, [fetchSancion]);

  const handleAddSeguimiento = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!nota.trim() && estado === "pendiente") return;
    setSubmitting(true);
    try {
      await api.sanciones.addSeguimiento(parseInt(id), { nota, estado });
      setNota("");
      const segs = await api.sanciones.getSeguimientos(parseInt(id));
      setSeguimientos(segs as unknown as Seguimiento[]);
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (!sancion) {
    return (
      <div className="bg-card rounded-xl border border-border p-8 text-center">
        <p className="text-muted-foreground">Sancion no encontrada.</p>
        <Link href="/sanciones" className="text-primary hover:underline text-sm mt-2 inline-block">
          Volver a sanciones
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <Link href="/sanciones" className="text-primary hover:underline text-sm">
          &larr; Sanciones
        </Link>
        <span className="text-muted-foreground">/</span>
        <h1 className="text-xl font-bold truncate">{sancion.nombre || "Sin nombre"}</h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main info */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
            <h2 className="text-lg font-semibold mb-4">Datos del sancionado</h2>
            <InfoRow label="Nombre" value={sancion.nombre} />
            <InfoRow label="Tipo persona" value={sancion.tipo_persona} />
            <InfoRow label="Identificador" value={sancion.identificador} />
            <InfoRow label="Tipo ID" value={sancion.tipo_identificador} />
            <InfoRow label="Direccion" value={sancion.direccion} />
            <InfoRow label="Telefono" value={sancion.telefono} />
            <InfoRow label="Email" value={sancion.email} />
            <InfoRow label="Matricula" value={sancion.matricula_coche} />
          </div>

          <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
            <h2 className="text-lg font-semibold mb-4">Detalles de la sancion</h2>
            <InfoRow label="Organismo emisor" value={sancion.organismo_emisor} />
            <InfoRow
              label="Importe multa"
              value={
                sancion.importe_multa_eur
                  ? `${sancion.importe_multa_eur.toLocaleString("es-ES")} EUR`
                  : null
              }
            />
            <InfoRow label="Tipo infraccion" value={sancion.tipo_infraccion?.replace("_", " ")} />
            <InfoRow label="Expediente" value={sancion.expediente} />
            <InfoRow label="Estado publicacion" value={sancion.estado_publicacion} />
            <InfoRow label="Dominio material" value={sancion.dominio_material} />
            {sancion.razon_sancion && (
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-1">Razon de la sancion</p>
                <p className="text-sm bg-muted p-3 rounded-lg">{sancion.razon_sancion}</p>
              </div>
            )}
          </div>

          <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
            <h2 className="text-lg font-semibold mb-4">Plazos y base legal</h2>
            <InfoRow label="Plazo notificacion" value={sancion.plazo_notificacion} />
            <InfoRow label="Plazo alegaciones" value={sancion.plazo_alegaciones} />
            <InfoRow label="Plazo recurso" value={sancion.plazo_recurso} />
            {sancion.base_legal && (
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-1">Base legal</p>
                <p className="text-sm bg-muted p-3 rounded-lg">{sancion.base_legal}</p>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
            <h2 className="text-lg font-semibold mb-4">Documento BOE</h2>
            <InfoRow label="BOE ID" value={sancion.boe_id} />
            <InfoRow label="Fecha publicacion" value={sancion.fecha_publicacion} />
            {sancion.titulo_documento && (
              <div className="mt-3">
                <p className="text-xs text-muted-foreground mb-1">Titulo</p>
                <p className="text-xs">{sancion.titulo_documento}</p>
              </div>
            )}
            {sancion.url_documento && (
              <a
                href={sancion.url_documento}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-block bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
              >
                Ver documento en BOE &rarr;
              </a>
            )}
          </div>

          {/* Seguimientos */}
          <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
            <h2 className="text-lg font-semibold mb-4">Seguimiento</h2>

            <form onSubmit={handleAddSeguimiento} className="space-y-3 mb-4">
              <select
                value={estado}
                onChange={(e) => setEstado(e.target.value)}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background"
              >
                {ESTADOS_SEGUIMIENTO.map((e) => (
                  <option key={e.value} value={e.value}>
                    {e.label}
                  </option>
                ))}
              </select>
              <textarea
                placeholder="Anadir nota..."
                value={nota}
                onChange={(e) => setNota(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background resize-none"
              />
              <button
                type="submit"
                disabled={submitting}
                className="w-full bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {submitting ? "Guardando..." : "Guardar seguimiento"}
              </button>
            </form>

            {seguimientos.length > 0 ? (
              <div className="space-y-3 max-h-64 overflow-y-auto">
                {seguimientos.map((seg) => {
                  const estadoInfo = ESTADOS_SEGUIMIENTO.find((e) => e.value === seg.estado);
                  return (
                    <div key={seg.id} className="border border-border rounded-lg p-3">
                      <div className="flex justify-between items-center mb-1">
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs font-medium ${estadoInfo?.color || "bg-gray-100 text-gray-800"}`}
                        >
                          {estadoInfo?.label || seg.estado}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {new Date(seg.created_at).toLocaleString("es-ES")}
                        </span>
                      </div>
                      {seg.nota && <p className="text-sm mt-1">{seg.nota}</p>}
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Sin seguimientos aun.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
