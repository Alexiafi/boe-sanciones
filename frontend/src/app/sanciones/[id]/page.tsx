"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { EnriquecimientoIntento, Sancionado, Seguimiento } from "@/lib/types";

function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return <div className="flex justify-between gap-4 py-2 border-b border-border last:border-0"><span className="text-sm text-muted-foreground">{label}</span><span className="text-sm font-medium text-right max-w-[60%]">{value}</span></div>;
}

const states = ["nueva", "revisada", "contactada", "descartada"] as const;

const contactoLabel: Record<string, string> = {
  pendiente: "Pendiente", encontrado: "Encontrado", no_encontrado: "No encontrado", manual: "Manual",
};
const contactoColor: Record<string, string> = {
  pendiente: "bg-gray-100 text-gray-800", encontrado: "bg-green-100 text-green-800",
  no_encontrado: "bg-red-100 text-red-800", manual: "bg-blue-100 text-blue-800",
};

export default function SancionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [sancion, setSancion] = useState<Sancionado | null>(null);
  const [seguimientos, setSeguimientos] = useState<Seguimiento[]>([]);
  const [intentos, setIntentos] = useState<EnriquecimientoIntento[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [estado, setEstado] = useState("nueva");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [web, setWeb] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [telefonoSecundario, setTelefonoSecundario] = useState("");
  const [nota, setNota] = useState("");
  const [enriching, setEnriching] = useState(false);
  const [enrichNotice, setEnrichNotice] = useState<string | null>(null);
  const [converting, setConverting] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await api.sanciones.get(Number(id)) as unknown as Sancionado;
      setSancion(result);
      setSeguimientos(result.seguimientos || []);
      setEstado(result.estado_oportunidad);
      setTelefono(result.telefono || "");
      setEmail(result.email || "");
      setWeb(result.web || "");
      setLinkedinUrl(result.linkedin_url || "");
      setTelefonoSecundario(result.telefono_secundario || "");
      setIntentos(await api.sanciones.enrichmentAttempts(Number(id)) as unknown as EnriquecimientoIntento[]);
    } catch (error) { console.error(error); setSancion(null); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const saveOpportunity = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice(null);
    try {
      const result = await api.sanciones.update(Number(id), {
        estado_oportunidad: estado,
        telefono: telefono || null,
        email: email || null,
        web: web || null,
        linkedin_url: linkedinUrl || null,
        telefono_secundario: telefonoSecundario || null,
      }) as unknown as Sancionado;
      setSancion(result); setNotice("Cambios guardados.");
    } catch (error) { setNotice(`No se pudieron guardar los cambios: ${error}`); } finally { setSaving(false); }
  };
  const addSeguimiento = async (event: React.FormEvent) => {
    event.preventDefault(); if (!nota.trim()) return;
    await api.sanciones.addSeguimiento(Number(id), { nota, estado: "pendiente" }); setNota("");
    setSeguimientos(await api.sanciones.getSeguimientos(Number(id)) as unknown as Seguimiento[]);
  };
  const enrichContact = async () => {
    setEnriching(true); setEnrichNotice(null);
    try {
      await api.sanciones.enrich(Number(id));
      setEnrichNotice("Enriquecimiento encolado. Los resultados tardan unos segundos en aparecer; recarga para verlos.");
    } catch (error) { setEnrichNotice(`No se pudo lanzar el enriquecimiento: ${error}`); } finally { setEnriching(false); }
  };
  const convertToClient = async () => {
    setConverting(true);
    try {
      const result = await api.sanciones.convertir(Number(id));
      router.push(`/clientes/${(result.cliente as { id: number }).id}`);
    } catch (error) { setNotice(`No se pudo convertir en cliente: ${error}`); setConverting(false); }
  };

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></div>;
  if (!sancion) return <div className="bg-card rounded-xl border border-border p-8 text-center"><p className="text-muted-foreground">Oportunidad no encontrada.</p><Link href="/sanciones" className="text-primary hover:underline text-sm mt-2 inline-block">Volver a oportunidades</Link></div>;
  const amount = sancion.importe_multa_eur ?? sancion.importe_deuda_eur;

  return <div>
    <div className="mb-6 flex items-center gap-3"><Link href="/sanciones" className="text-primary hover:underline text-sm">← Oportunidades</Link><span className="text-muted-foreground">/</span><h1 className="text-xl font-bold truncate">{sancion.codigo} · {sancion.nombre || sancion.identificador || "Sin identificar"}</h1></div>
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6"><div className="lg:col-span-2 space-y-6">
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Datos extraídos</h2><InfoRow label="Nombre" value={sancion.nombre} /><InfoRow label="Tipo de persona" value={sancion.tipo_persona} /><InfoRow label="Identificador" value={sancion.identificador} /><InfoRow label="Dirección" value={sancion.direccion} /><InfoRow label="Localidad" value={sancion.localidad} /><InfoRow label="Provincia" value={sancion.provincia} /><InfoRow label="Código postal" value={sancion.codigo_postal} /><InfoRow label="Matrícula" value={sancion.matricula_coche} /></section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Expediente</h2><InfoRow label="Materia" value={sancion.dominio_material} /><InfoRow label="Procedimiento" value={sancion.tipo_procedimiento} /><InfoRow label="Organismo" value={sancion.organismo_emisor} /><InfoRow label="Expediente" value={sancion.expediente} /><InfoRow label="Cuantía" value={amount == null ? null : `${amount.toLocaleString("es-ES")} €`} /><InfoRow label="Fecha de resolución" value={sancion.fecha_resolucion} /><InfoRow label="Plazo de pago voluntario" value={sancion.plazo_pago_voluntario} /><InfoRow label="Motivo" value={sancion.razon_sancion} /><InfoRow label="Observaciones" value={sancion.observaciones} /></section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Contacto</h2>
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${contactoColor[sancion.contacto_estado]}`}>{contactoLabel[sancion.contacto_estado]}</span>
        </div>
        <InfoRow label="Teléfono" value={sancion.telefono} />
        <InfoRow label="Teléfono secundario" value={sancion.telefono_secundario} />
        <InfoRow label="Email" value={sancion.email} />
        <InfoRow label="Web" value={sancion.web} />
        {sancion.linkedin_url && <div className="flex justify-between gap-4 py-2 border-b border-border last:border-0"><span className="text-sm text-muted-foreground">LinkedIn</span><a href={sancion.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline text-right max-w-[60%] truncate">{sancion.linkedin_url}</a></div>}
        {sancion.contacto_estado !== "pendiente" && (
          <div className="mt-3 text-xs text-muted-foreground space-y-1">
            {sancion.contacto_fuente && <p>Fuente: {sancion.contacto_fuente}{sancion.contacto_confidence != null && ` · confianza ${(sancion.contacto_confidence * 100).toFixed(0)}%`}</p>}
            {sancion.contacto_url && <p>Origen: <a href={sancion.contacto_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{sancion.contacto_url}</a></p>}
            {sancion.contacto_actualizado_at && <p>Actualizado: {new Date(sancion.contacto_actualizado_at).toLocaleString("es-ES")}</p>}
          </div>
        )}
        <div className="mt-4 flex items-center gap-3">
          <button onClick={enrichContact} disabled={enriching} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm disabled:opacity-50">{enriching ? "Encolando…" : "Enriquecer contacto"}</button>
        </div>
        {enrichNotice && <p className="mt-2 text-xs text-muted-foreground">{enrichNotice}</p>}
        {intentos.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Historial de intentos</p>
            {intentos.map((intento) => (
              <div key={intento.id} className="border border-border rounded-lg p-2 text-xs">
                <span className="font-medium">{intento.resultado}</span>
                <span className="text-muted-foreground"> · {intento.proveedor} · {new Date(intento.created_at).toLocaleString("es-ES")}</span>
                {intento.evidencia && <p className="text-muted-foreground mt-1">{intento.evidencia}</p>}
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Seguimiento</h2><form onSubmit={addSeguimiento} className="flex gap-3 mb-4"><input value={nota} onChange={(event) => setNota(event.target.value)} placeholder="Añadir nota" className="flex-1 px-3 py-2 border border-border rounded-lg text-sm bg-background" /><button className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm">Guardar nota</button></form>{seguimientos.length ? <div className="space-y-2">{seguimientos.map((item) => <div key={item.id} className="border border-border rounded-lg p-3 text-sm"><span className="text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString("es-ES")}</span><p>{item.nota || "Sin nota"}</p></div>)}</div> : <p className="text-sm text-muted-foreground">Sin seguimientos todavía.</p>}</section>
    </div><aside className="space-y-6">
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Editar oportunidad</h2><form onSubmit={saveOpportunity} className="space-y-3"><label className="block text-sm">Estado<select value={estado} onChange={(event) => setEstado(event.target.value)} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background">{states.map((value) => <option key={value}>{value}</option>)}</select></label><label className="block text-sm">Teléfono<input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><label className="block text-sm">Teléfono secundario<input value={telefonoSecundario} onChange={(event) => setTelefonoSecundario(event.target.value)} maxLength={50} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><label className="block text-sm">Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><label className="block text-sm">Web<input value={web} onChange={(event) => setWeb(event.target.value)} maxLength={500} placeholder="https://…" className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><label className="block text-sm">LinkedIn (enlace añadido a mano)<input value={linkedinUrl} onChange={(event) => setLinkedinUrl(event.target.value)} maxLength={500} placeholder="https://linkedin.com/…" className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label><button disabled={saving} className="w-full bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm disabled:opacity-50">{saving ? "Guardando…" : "Guardar cambios"}</button>{notice && <p className="text-xs text-muted-foreground">{notice}</p>}</form></section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-3">Conversión</h2>
        {sancion.cliente_id ? (
          <Link href={`/clientes/${sancion.cliente_id}`} className="w-full inline-block text-center bg-muted text-foreground px-4 py-2 rounded-lg text-sm">Ver ficha de cliente →</Link>
        ) : (
          <button onClick={convertToClient} disabled={converting} className="w-full bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm disabled:opacity-50">{converting ? "Convirtiendo…" : "Convertir en cliente"}</button>
        )}
      </section>
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm"><h2 className="text-lg font-semibold mb-4">Documento BOE</h2><InfoRow label="BOE" value={sancion.boe_id} /><InfoRow label="Publicación" value={sancion.fecha_publicacion} />{sancion.titulo_documento && <p className="text-xs text-muted-foreground mt-3">{sancion.titulo_documento}</p>}{sancion.url_documento && <a href={sancion.url_documento} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm">Ver documento oficial →</a>}</section>
    </aside></div>
  </div>;
}
