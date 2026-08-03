"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Sancionado, Seguimiento } from "@/lib/types";

function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return <div className="flex justify-between gap-4 py-2 border-b border-border last:border-0"><span className="text-sm text-muted-foreground">{label}</span><span className="text-sm font-medium text-right max-w-[60%]">{value}</span></div>;
}

const states = ["nueva", "revisada", "contactada", "descartada"] as const;

export default function SancionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [sancion, setSancion] = useState<Sancionado | null>(null);
  const [seguimientos, setSeguimientos] = useState<Seguimiento[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [estado, setEstado] = useState("nueva");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [nota, setNota] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await api.sanciones.get(Number(id)) as unknown as Sancionado;
      setSancion(result); setSeguimientos(result.seguimientos || []); setEstado(result.estado_oportunidad); setTelefono(result.telefono || ""); setEmail(result.email || "");
    } catch (error) { console.error(error); setSancion(null); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const saveOpportunity = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice(null);
    try {
      const result = await api.sanciones.update(Number(id), { estado_oportunidad: estado, telefono: telefono || null, email: email || null }) as unknown as Sancionado;
      setSancion(result); setNotice("Cambios guardados.");
    } catch (error) { setNotice(`No se pudieron guardar los cambios: ${error}`); } finally { setSaving(false); }
  };
  const addSeguimiento = async (event: React.FormEvent) => {
    event.preventDefault(); if (!nota.trim()) return;
    await api.sanciones.addSeguimiento(Number(id), { nota, estado: "pendiente" }); setNota("");
    setSeguimientos(await api.sanciones.getSeguimientos(Number(id)) as unknown as Seguimiento[]);
  };

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></div>;
  if (!sancion) return <div className="bg-card rounded-xl border border-border p-8 text-center"><p className="text-muted-foreground">Oportunidad no encontrada.</p><Link href="/sanciones" className="text-primary hover:underline text-sm mt-2 inline-block">Volver a oportunidades</Link></div>;
  const amount = sancion.importe_multa_eur ?? sancion.importe_deuda_eur;

  return <div>
    <div className="mb-6 flex items-center gap-3"><Link href="/sanciones" className="text-primary hover:underline text-sm">← Oportunidades</Link><span className="text-muted-foreground">/</span><h1 className="text-xl font-bold truncate">{sancion.codigo} · {sancion.nombre || sancion.identificador || "Sin identificar"}</h1></div>
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6"><div className="lg:col-span-2 space-y-6">
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Datos extraídos</h2><InfoRow label="Nombre" value={sancion.nombre} /><InfoRow label="Tipo de persona" value={sancion.tipo_persona} /><InfoRow label="Identificador" value={sancion.identificador} /><InfoRow label="Dirección" value={sancion.direccion} /><InfoRow label="Localidad" value={sancion.localidad} /><InfoRow label="Provincia" value={sancion.provincia} /><InfoRow label="Código postal" value={sancion.codigo_postal} /><InfoRow label="Matrícula" value={sancion.matricula_coche} /></section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Expediente</h2><InfoRow label="Materia" value={sancion.dominio_material} /><InfoRow label="Procedimiento" value={sancion.tipo_procedimiento} /><InfoRow label="Organismo" value={sancion.organismo_emisor} /><InfoRow label="Expediente" value={sancion.expediente} /><InfoRow label="Cuantía" value={amount == null ? null : `${amount.toLocaleString("es-ES")} €`} /><InfoRow label="Fecha de resolución" value={sancion.fecha_resolucion} /><InfoRow label="Plazo de pago voluntario" value={sancion.plazo_pago_voluntario} /><InfoRow label="Motivo" value={sancion.razon_sancion} /><InfoRow label="Observaciones" value={sancion.observaciones} /></section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Seguimiento</h2><form onSubmit={addSeguimiento} className="flex gap-3 mb-4"><input value={nota} onChange={(event) => setNota(event.target.value)} placeholder="Añadir nota" className="flex-1 px-3 py-2 border border-border rounded-lg text-sm bg-background" /><button className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm">Guardar nota</button></form>{seguimientos.length ? <div className="space-y-2">{seguimientos.map((item) => <div key={item.id} className="border border-border rounded-lg p-3 text-sm"><span className="text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString("es-ES")}</span><p>{item.nota || "Sin nota"}</p></div>)}</div> : <p className="text-sm text-muted-foreground">Sin seguimientos todavía.</p>}</section>
    </div><aside className="space-y-6">
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Editar oportunidad</h2><form onSubmit={saveOpportunity} className="space-y-3"><label className="block text-sm">Estado<select value={estado} onChange={(event) => setEstado(event.target.value)} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background">{states.map((value) => <option key={value}>{value}</option>)}</select></label><label className="block text-sm">Teléfono<input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><label className="block text-sm">Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><button disabled={saving} className="w-full bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm disabled:opacity-50">{saving ? "Guardando…" : "Guardar cambios"}</button>{notice && <p className="text-xs text-muted-foreground">{notice}</p>}</form></section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Documento BOE</h2><InfoRow label="BOE" value={sancion.boe_id} /><InfoRow label="Publicación" value={sancion.fecha_publicacion} />{sancion.titulo_documento && <p className="text-xs text-muted-foreground mt-3">{sancion.titulo_documento}</p>}{sancion.url_documento && <a href={sancion.url_documento} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm">Ver documento oficial →</a>}</section>
    </aside></div>
  </div>;
}
