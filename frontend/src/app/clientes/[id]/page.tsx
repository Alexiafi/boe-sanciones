"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { AccionAgendada, ClienteDetail } from "@/lib/types";

function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return <div className="flex justify-between gap-4 py-2 border-b border-border last:border-0"><span className="text-sm text-muted-foreground">{label}</span><span className="text-sm font-medium text-right max-w-[60%]">{value}</span></div>;
}

const estadoLabel: Record<string, string> = { activo: "Activo", inactivo: "Inactivo" };
const accionEstadoColor: Record<string, string> = {
  pendiente: "bg-blue-100 text-blue-800", hecha: "bg-green-100 text-green-800", cancelada: "bg-gray-100 text-gray-800",
};

export default function ClienteDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [cliente, setCliente] = useState<ClienteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [estadoCliente, setEstadoCliente] = useState("activo");
  const [personaContacto, setPersonaContacto] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [web, setWeb] = useState("");
  const [sector, setSector] = useState("");

  const [nota, setNota] = useState("");
  const [accionTitulo, setAccionTitulo] = useState("");
  const [accionTipo, setAccionTipo] = useState<"llamada" | "email" | "tarea">("llamada");

  const load = useCallback(async () => {
    try {
      const result = await api.clientes.get(Number(id)) as unknown as ClienteDetail;
      setCliente(result);
      setEstadoCliente(result.estado_cliente);
      setPersonaContacto(result.persona_contacto || "");
      setTelefono(result.telefono || "");
      setEmail(result.email || "");
      setWeb(result.web || "");
      setSector(result.sector || "");
    } catch (error) { console.error(error); setCliente(null); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const saveCliente = async (event: React.FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice(null);
    try {
      await api.clientes.update(Number(id), {
        estado_cliente: estadoCliente,
        persona_contacto: personaContacto || null,
        telefono: telefono || null,
        email: email || null,
        web: web || null,
        sector: sector || null,
      });
      await load();
      setNotice("Cambios guardados.");
    } catch (error) { setNotice(`No se pudieron guardar los cambios: ${error}`); } finally { setSaving(false); }
  };

  const addNota = async (event: React.FormEvent) => {
    event.preventDefault(); if (!nota.trim()) return;
    await api.clientes.addNota(Number(id), { texto: nota }); setNota("");
    await load();
  };

  const addAccion = async (event: React.FormEvent) => {
    event.preventDefault(); if (!accionTitulo.trim()) return;
    await api.clientes.addAccion(Number(id), { tipo: accionTipo, titulo: accionTitulo }); setAccionTitulo("");
    await load();
  };

  const marcarAccion = async (accion: AccionAgendada, estado: "hecha" | "cancelada") => {
    await api.clientes.updateAccion(Number(id), accion.id, { estado });
    await load();
  };

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></div>;
  if (!cliente) return <div className="bg-card rounded-xl border border-border p-8 text-center"><p className="text-muted-foreground">Cliente no encontrado.</p><Link href="/clientes" className="text-primary hover:underline text-sm mt-2 inline-block">Volver a clientes</Link></div>;

  return <div>
    <div className="mb-6 flex items-center gap-3">
      <Link href="/clientes" className="text-primary hover:underline text-sm">← Clientes</Link>
      <span className="text-muted-foreground">/</span>
      <h1 className="text-xl font-bold truncate">{cliente.codigo} · {cliente.nombre_razon_social}</h1>
      <span className={`px-2 py-0.5 rounded-full text-xs ${cliente.estado_cliente === "activo" ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-800"}`}>{estadoLabel[cliente.estado_cliente]}</span>
    </div>
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6"><div className="lg:col-span-2 space-y-6">
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Datos del cliente</h2>
        <InfoRow label="Tipo de persona" value={cliente.tipo_persona} />
        <InfoRow label="CIF/NIF" value={cliente.cif_nif} />
        <InfoRow label="DNI/NIE" value={cliente.dni_nie} />
        <InfoRow label="Matrículas" value={cliente.matriculas?.length ? cliente.matriculas.join(", ") : null} />
        <InfoRow label="Dirección fiscal" value={cliente.direccion_fiscal} />
        <InfoRow label="Localidad" value={cliente.localidad} />
        <InfoRow label="Provincia" value={cliente.provincia} />
        <InfoRow label="Deuda pendiente" value={cliente.deuda_pendiente_eur ? `${cliente.deuda_pendiente_eur.toLocaleString("es-ES")} €` : null} />
        <InfoRow label="Fecha de contrato" value={cliente.fecha_contrato} />
        <InfoRow label="Precio de contrato" value={cliente.precio_contrato ? `${cliente.precio_contrato.toLocaleString("es-ES")} €` : null} />
      </section>

      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Sanciones vinculadas</h2>
        {cliente.sanciones.length ? (
          <div className="space-y-2">{cliente.sanciones.map((item) => (
            <div key={item.id} className="border border-border rounded-lg p-3 text-sm flex items-center justify-between">
              <div>
                <span className="font-mono text-xs">{item.codigo}</span>
                <span className="text-muted-foreground ml-2">{item.fecha_publicacion}</span>
                {(item.importe_multa_eur ?? item.importe_deuda_eur) != null && (
                  <span className="ml-2">{(item.importe_multa_eur ?? item.importe_deuda_eur)!.toLocaleString("es-ES")} €</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {item.url_documento && <a href={item.url_documento} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">Ver BOE</a>}
                <Link href={`/sanciones/${item.id}`} className="text-xs text-primary hover:underline">Detalle</Link>
              </div>
            </div>
          ))}</div>
        ) : <p className="text-sm text-muted-foreground">Sin sanciones vinculadas.</p>}
      </section>

      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Notas del cliente</h2>
        <form onSubmit={addNota} className="flex gap-3 mb-4">
          <input value={nota} onChange={(event) => setNota(event.target.value)} placeholder="Añadir nota" className="flex-1 px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <button className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm">Guardar</button>
        </form>
        {cliente.notas.length ? (
          <div className="space-y-2">{cliente.notas.map((item) => (
            <div key={item.id} className="border border-border rounded-lg p-3 text-sm">
              <span className="text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString("es-ES")}{item.autor ? ` · ${item.autor}` : ""}</span>
              <p>{item.texto}</p>
            </div>
          ))}</div>
        ) : <p className="text-sm text-muted-foreground">Sin notas todavía.</p>}
      </section>

      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Registro de actividad</h2>
        {cliente.actividades.length ? (
          <div className="space-y-2">{cliente.actividades.map((item) => (
            <div key={item.id} className="border border-border rounded-lg p-3 text-sm">
              <span className="text-xs text-muted-foreground">{new Date(item.created_at).toLocaleString("es-ES")} · {item.tipo}</span>
              <p className="font-medium">{item.titulo}</p>
              {item.detalle && <p className="text-muted-foreground text-xs mt-1">{item.detalle}</p>}
            </div>
          ))}</div>
        ) : <p className="text-sm text-muted-foreground">Sin actividad registrada.</p>}
      </section>
    </div>

    <aside className="space-y-6">
      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Editar cliente</h2>
        <form onSubmit={saveCliente} className="space-y-3">
          <label className="block text-sm">Estado<select value={estadoCliente} onChange={(event) => setEstadoCliente(event.target.value)} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background"><option value="activo">Activo</option><option value="inactivo">Inactivo</option></select></label>
          <label className="block text-sm">Persona de contacto<input value={personaContacto} onChange={(event) => setPersonaContacto(event.target.value)} maxLength={200} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label>
          <label className="block text-sm">Teléfono<input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label>
          <label className="block text-sm">Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label>
          <label className="block text-sm">Web<input value={web} onChange={(event) => setWeb(event.target.value)} maxLength={500} placeholder="https://…" className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label>
          <label className="block text-sm">Sector<input value={sector} onChange={(event) => setSector(event.target.value)} maxLength={200} className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background" /></label>
          <button disabled={saving} className="w-full bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm disabled:opacity-50">{saving ? "Guardando…" : "Guardar cambios"}</button>
          {notice && <p className="text-xs text-muted-foreground">{notice}</p>}
        </form>
      </section>

      <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
        <h2 className="text-lg font-semibold mb-4">Acciones</h2>
        <form onSubmit={addAccion} className="space-y-2 mb-4">
          <select value={accionTipo} onChange={(event) => setAccionTipo(event.target.value as typeof accionTipo)} className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background">
            <option value="llamada">Llamada</option><option value="email">Email</option><option value="tarea">Tarea</option>
          </select>
          <input value={accionTitulo} onChange={(event) => setAccionTitulo(event.target.value)} placeholder="p. ej. Agendar llamada" className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <button className="w-full bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm">Agendar</button>
        </form>
        {cliente.acciones.length ? (
          <div className="space-y-2">{cliente.acciones.map((accion) => (
            <div key={accion.id} className="border border-border rounded-lg p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium">{accion.titulo}</span>
                <span className={`px-2 py-0.5 rounded-full text-xs ${accionEstadoColor[accion.estado]}`}>{accion.estado}</span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">{accion.tipo} · {new Date(accion.created_at).toLocaleString("es-ES")}</p>
              {accion.estado === "pendiente" && (
                <div className="mt-2 flex gap-2">
                  <button onClick={() => marcarAccion(accion, "hecha")} className="text-xs text-primary hover:underline">Marcar hecha</button>
                  <button onClick={() => marcarAccion(accion, "cancelada")} className="text-xs text-muted-foreground hover:underline">Cancelar</button>
                </div>
              )}
            </div>
          ))}</div>
        ) : <p className="text-sm text-muted-foreground">Sin acciones agendadas.</p>}
      </section>
    </aside>
    </div>
  </div>;
}
