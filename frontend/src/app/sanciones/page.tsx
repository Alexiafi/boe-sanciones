"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { PaginatedResponse, Sancionado } from "@/lib/types";

function dateInput(daysAgo: number) {
  const value = new Date();
  value.setDate(value.getDate() - daysAgo);
  return value.toISOString().slice(0, 10);
}

const estadoLabel: Record<string, string> = {
  nueva: "Nueva", revisada: "Revisada", contactada: "Contactada", descartada: "Descartada", cliente: "Cliente",
};

export default function SancionesPage() {
  const [data, setData] = useState<PaginatedResponse<Sancionado> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [estado, setEstado] = useState("");
  const [materia, setMateria] = useState("");
  const [persona, setPersona] = useState("");
  const [contacto, setContacto] = useState("");
  const [cuantiaMin, setCuantiaMin] = useState("");
  const [cuantiaMax, setCuantiaMax] = useState("");
  const [fechaDesde, setFechaDesde] = useState(() => dateInput(29));
  const [fechaHasta, setFechaHasta] = useState(() => dateInput(0));

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(page), page_size: "20", fecha_desde: fechaDesde, fecha_hasta: fechaHasta };
      if (search) params.search = search;
      if (estado) params.estado_oportunidad = estado;
      if (materia) params.materia = materia;
      if (persona) params.tipo_persona = persona;
      if (contacto) params.solo_con_contacto = contacto;
      if (cuantiaMin) params.cuantia_min = cuantiaMin;
      if (cuantiaMax) params.cuantia_max = cuantiaMax;
      setData(await api.sanciones.list(params) as unknown as PaginatedResponse<Sancionado>);
    } catch (error) {
      console.error(error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [page, search, estado, materia, persona, contacto, cuantiaMin, cuantiaMax, fechaDesde, fechaHasta]);

  useEffect(() => { fetchData(); }, [fetchData]);
  const resetPage = () => setPage(1);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Oportunidades</h1>
        <p className="text-muted-foreground mt-1">Publicaciones BOE de los últimos 30 días. Consultar esta lista no inicia scraping.</p>
      </div>
      <form onSubmit={(event) => { event.preventDefault(); resetPage(); fetchData(); }} className="bg-card rounded-xl border border-border p-4 mb-6 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <input placeholder="Código, nombre, identificador o expediente" value={search} onChange={(event) => { setSearch(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <select value={estado} onChange={(event) => { setEstado(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background">
            <option value="">Todos los estados</option>
            {Object.entries(estadoLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <input placeholder="Materia (texto libre)" value={materia} onChange={(event) => { setMateria(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <select value={persona} onChange={(event) => { setPersona(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background">
            <option value="">Persona física o jurídica</option><option value="fisica">Física</option><option value="juridica">Jurídica</option>
          </select>
          <input type="date" aria-label="Publicada desde" value={fechaDesde} onChange={(event) => { setFechaDesde(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <input type="date" aria-label="Publicada hasta" value={fechaHasta} onChange={(event) => { setFechaHasta(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <input type="number" min="0" placeholder="Cuantía mínima" value={cuantiaMin} onChange={(event) => { setCuantiaMin(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <input type="number" min="0" placeholder="Cuantía máxima" value={cuantiaMax} onChange={(event) => { setCuantiaMax(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <select value={contacto} onChange={(event) => { setContacto(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background"><option value="">Todo contacto</option><option value="true">Con contacto</option><option value="false">Sin contacto</option></select>
          <button type="submit" className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium">Aplicar filtros</button>
        </div>
      </form>
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        {loading ? <div className="flex items-center justify-center h-48"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></div> : !data?.items.length ? <div className="p-8 text-center text-muted-foreground">No se encontraron oportunidades.</div> : <>
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-muted border-b border-border"><tr>
            {['Código','Nombre / razón social','Identificador','Materia','Cuantía','Estado','Contacto','Fecha','BOE',''].map((title) => <th key={title} className="text-left px-4 py-3 font-medium text-muted-foreground">{title}</th>)}
          </tr></thead><tbody className="divide-y divide-border">{data.items.map((item) => {
            const amount = item.importe_multa_eur ?? item.importe_deuda_eur;
            return <tr key={item.id} className="hover:bg-muted/50"><td className="px-4 py-3 font-mono text-xs">{item.codigo}</td><td className="px-4 py-3 font-medium max-w-[180px] truncate">{item.nombre || "—"}</td><td className="px-4 py-3 text-muted-foreground">{item.identificador || "—"}</td><td className="px-4 py-3">{item.dominio_material || "—"}</td><td className="px-4 py-3">{amount == null ? "—" : `${amount.toLocaleString("es-ES")} €`}</td><td className="px-4 py-3"><span className="px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-800">{estadoLabel[item.estado_oportunidad]}</span></td><td className="px-4 py-3 text-xs">{item.telefono || item.email || "—"}</td><td className="px-4 py-3 text-muted-foreground">{item.fecha_publicacion}</td><td className="px-4 py-3">{item.url_documento ? <a href={item.url_documento} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline text-xs">Ver</a> : "—"}</td><td className="px-4 py-3"><Link href={`/sanciones/${item.id}`} className="text-primary hover:underline text-xs">Detalle</Link></td></tr>;
          })}</tbody></table></div>
          <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/30"><p className="text-xs text-muted-foreground">{data.total} resultados · Página {data.page} de {data.pages}</p><div className="flex gap-2"><button onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1} className="px-3 py-1 text-xs border border-border rounded-md disabled:opacity-50">Anterior</button><button onClick={() => setPage((value) => Math.min(data.pages, value + 1))} disabled={page >= data.pages} className="px-3 py-1 text-xs border border-border rounded-md disabled:opacity-50">Siguiente</button></div></div>
        </>}
      </div>
    </div>
  );
}
