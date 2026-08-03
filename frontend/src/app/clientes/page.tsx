"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Cliente, PaginatedResponse } from "@/lib/types";

const estadoLabel: Record<string, string> = { activo: "Activo", inactivo: "Inactivo" };
const estadoColor: Record<string, string> = { activo: "bg-green-100 text-green-800", inactivo: "bg-gray-100 text-gray-800" };

export default function ClientesPage() {
  const [data, setData] = useState<PaginatedResponse<Cliente> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [estado, setEstado] = useState("");
  const [sector, setSector] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(page), page_size: "20" };
      if (search) params.search = search;
      if (estado) params.estado_cliente = estado;
      if (sector) params.sector = sector;
      setData(await api.clientes.list(params) as unknown as PaginatedResponse<Cliente>);
    } catch (error) {
      console.error(error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [page, search, estado, sector]);

  useEffect(() => { fetchData(); }, [fetchData]);
  const resetPage = () => setPage(1);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Clientes</h1>
        <p className="text-muted-foreground mt-1">Directorio de oportunidades convertidas en clientes.</p>
      </div>
      <form onSubmit={(event) => { event.preventDefault(); resetPage(); fetchData(); }} className="bg-card rounded-xl border border-border p-4 mb-6 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <input placeholder="Razón social, CIF/NIF o código" value={search} onChange={(event) => { setSearch(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <select value={estado} onChange={(event) => { setEstado(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background">
            <option value="">Todos los estados</option>
            {Object.entries(estadoLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <input placeholder="Sector" value={sector} onChange={(event) => { setSector(event.target.value); resetPage(); }} className="px-3 py-2 border border-border rounded-lg text-sm bg-background" />
          <button type="submit" className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium">Aplicar filtros</button>
        </div>
      </form>
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        {loading ? <div className="flex items-center justify-center h-48"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" /></div> : !data?.items.length ? <div className="p-8 text-center text-muted-foreground">No se encontraron clientes. Convierte una oportunidad desde su detalle para verla aquí.</div> : <>
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-muted border-b border-border"><tr>
            {['Código', 'Razón social', 'CIF/NIF', 'Contacto', 'Deuda pendiente', 'Estado', 'Sector', ''].map((title) => <th key={title} className="text-left px-4 py-3 font-medium text-muted-foreground">{title}</th>)}
          </tr></thead><tbody className="divide-y divide-border">{data.items.map((item) => (
            <tr key={item.id} className="hover:bg-muted/50">
              <td className="px-4 py-3 font-mono text-xs">{item.codigo}</td>
              <td className="px-4 py-3 font-medium max-w-[220px] truncate">{item.nombre_razon_social}</td>
              <td className="px-4 py-3 text-muted-foreground">{item.cif_nif || item.dni_nie || "—"}</td>
              <td className="px-4 py-3 text-xs">{item.telefono || item.email || "—"}</td>
              <td className="px-4 py-3">{item.deuda_pendiente_eur ? `${item.deuda_pendiente_eur.toLocaleString("es-ES")} €` : "—"}</td>
              <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full text-xs ${estadoColor[item.estado_cliente]}`}>{estadoLabel[item.estado_cliente]}</span></td>
              <td className="px-4 py-3 text-muted-foreground">{item.sector || "—"}</td>
              <td className="px-4 py-3"><Link href={`/clientes/${item.id}`} className="text-primary hover:underline text-xs">Ver ficha</Link></td>
            </tr>
          ))}</tbody></table></div>
          <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/30"><p className="text-xs text-muted-foreground">{data.total} resultados · Página {data.page} de {data.pages}</p><div className="flex gap-2"><button onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1} className="px-3 py-1 text-xs border border-border rounded-md disabled:opacity-50">Anterior</button><button onClick={() => setPage((value) => Math.min(data.pages, value + 1))} disabled={page >= data.pages} className="px-3 py-1 text-xs border border-border rounded-md disabled:opacity-50">Siguiente</button></div></div>
        </>}
      </div>
    </div>
  );
}
