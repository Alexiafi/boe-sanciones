"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { PaginatedResponse, Sancionado } from "@/lib/types";

export default function SancionesPage() {
  const [data, setData] = useState<PaginatedResponse<Sancionado> | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [tipoInfraccion, setTipoInfraccion] = useState("");
  const [fechaDesde, setFechaDesde] = useState("");
  const [fechaHasta, setFechaHasta] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        page: page.toString(),
        page_size: "20",
      };
      if (search) params.search = search;
      if (tipoInfraccion) params.tipo_infraccion = tipoInfraccion;
      if (fechaDesde) params.fecha_desde = fechaDesde;
      if (fechaHasta) params.fecha_hasta = fechaHasta;

      const res = await api.sanciones.list(params);
      setData(res as unknown as PaginatedResponse<Sancionado>);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [page, search, tipoInfraccion, fechaDesde, fechaHasta]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchData();
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Sanciones</h1>
        <p className="text-muted-foreground mt-1">
          Listado de entidades y personas sancionadas en el BOE
        </p>
      </div>

      {/* Filters */}
      <form onSubmit={handleSearch} className="bg-card rounded-xl border border-border p-4 mb-6 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
          <input
            type="text"
            placeholder="Buscar por nombre, CIF/NIF, expediente..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ring bg-background"
          />
          <select
            value={tipoInfraccion}
            onChange={(e) => { setTipoInfraccion(e.target.value); setPage(1); }}
            className="px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ring bg-background"
          >
            <option value="">Todas las infracciones</option>
            <option value="leve">Leve</option>
            <option value="grave">Grave</option>
            <option value="muy_grave">Muy grave</option>
          </select>
          <input
            type="date"
            value={fechaDesde}
            onChange={(e) => { setFechaDesde(e.target.value); setPage(1); }}
            className="px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ring bg-background"
          />
          <input
            type="date"
            value={fechaHasta}
            onChange={(e) => { setFechaHasta(e.target.value); setPage(1); }}
            className="px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-ring bg-background"
          />
          <button
            type="submit"
            className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Buscar
          </button>
        </div>
      </form>

      {/* Table */}
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-48">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            No se encontraron sanciones.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted border-b border-border">
                  <tr>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Nombre</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">ID</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Organismo</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Tipo</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Multa</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Fecha</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">Estado</th>
                    <th className="text-left px-4 py-3 font-medium text-muted-foreground">BOE</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.items.map((s) => (
                    <tr key={s.id} className="hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-3 font-medium max-w-[200px] truncate">
                        {s.nombre || "-"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                        {s.identificador || "-"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground max-w-[200px] truncate">
                        {s.organismo_emisor || "-"}
                      </td>
                      <td className="px-4 py-3">
                        {s.tipo_infraccion ? (
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                              s.tipo_infraccion === "muy_grave"
                                ? "bg-red-100 text-red-800"
                                : s.tipo_infraccion === "grave"
                                  ? "bg-orange-100 text-orange-800"
                                  : "bg-yellow-100 text-yellow-800"
                            }`}
                          >
                            {s.tipo_infraccion.replace("_", " ")}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-4 py-3 font-medium">
                        {s.importe_multa_eur
                          ? `${s.importe_multa_eur.toLocaleString("es-ES")} EUR`
                          : "-"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {s.fecha_publicacion || "-"}
                      </td>
                      <td className="px-4 py-3">
                        {s.estado_publicacion ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-800">
                            {s.estado_publicacion}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {s.url_documento ? (
                          <a
                            href={s.url_documento}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline text-xs font-medium"
                            title={s.boe_id || "Ver documento"}
                          >
                            {s.boe_id || "Ver"}
                          </a>
                        ) : (
                          <span className="text-muted-foreground text-xs">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          href={`/sanciones/${s.id}`}
                          className="text-primary hover:underline text-xs font-medium"
                        >
                          Ver detalle
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/30">
              <p className="text-xs text-muted-foreground">
                {data.total} resultados | Pagina {data.page} de {data.pages}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="px-3 py-1 text-xs border border-border rounded-md hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Anterior
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
                  disabled={page >= data.pages}
                  className="px-3 py-1 text-xs border border-border rounded-md hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Siguiente
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
