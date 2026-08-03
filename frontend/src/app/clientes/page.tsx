"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Cliente, PaginatedResponse } from "@/lib/types";
import { Card, EmptyState, ErrorState, EstadoChip, Field, Input, PageHeader, Pagination, Select, Spinner } from "@/components/ui";
import { formatCurrency } from "@/lib/formatters";

export default function ClientesPage() {
  const [data, setData] = useState<PaginatedResponse<Cliente> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [estado, setEstado] = useState("");
  const [sector, setSector] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const params: Record<string, string> = { page: String(page), page_size: "20" };
      if (search) params.search = search;
      if (estado) params.estado_cliente = estado;
      if (sector) params.sector = sector;
      setData((await api.clientes.list(params)) as unknown as PaginatedResponse<Cliente>);
    } catch {
      setError(true);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [page, search, estado, sector]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);
  const resetPage = () => setPage(1);

  return (
    <div>
      <PageHeader title="Clientes" description="Directorio de oportunidades convertidas en clientes." />

      <Card className="mb-6">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            resetPage();
            fetchData();
          }}
          className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4"
        >
          <Field label="Búsqueda">
            <Input placeholder="Razón social, CIF/NIF o código" value={search} onChange={(event) => { setSearch(event.target.value); resetPage(); }} />
          </Field>
          <Field label="Estado">
            <Select value={estado} onChange={(event) => { setEstado(event.target.value); resetPage(); }}>
              <option value="">Todos los estados</option>
              <option value="activo">Activo</option>
              <option value="inactivo">Inactivo</option>
            </Select>
          </Field>
          <Field label="Sector">
            <Input placeholder="Sector" value={sector} onChange={(event) => { setSector(event.target.value); resetPage(); }} />
          </Field>
          <div className="flex items-end">
            <button type="submit" className="gradient-primary w-full rounded-lg px-4 py-2.5 text-sm font-medium text-on-primary shadow-ambient">
              Aplicar filtros
            </button>
          </div>
        </form>
      </Card>

      <Card className="p-0 overflow-hidden">
        {loading && <Spinner />}
        {!loading && error && (
          <div className="p-6">
            <ErrorState onRetry={fetchData} />
          </div>
        )}
        {!loading && !error && !data?.items.length && (
          <div className="p-6">
            <EmptyState
              title="No se encontraron clientes."
              description="Convierte una oportunidad desde su detalle para verla aquí."
            />
          </div>
        )}
        {!loading && !error && !!data?.items.length && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-container-low">
                  <tr>
                    {["Código", "Razón social", "CIF/NIF", "Contacto", "Deuda pendiente", "Estado", "Sector", ""].map((title) => (
                      <th key={title} scope="col" className="px-4 py-3 text-left font-medium text-on-surface-variant">
                        {title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.id} className="hover:bg-surface-container-low">
                      <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{item.codigo}</td>
                      <td className="max-w-[220px] truncate px-4 py-2.5 font-medium text-on-surface">{item.nombre_razon_social}</td>
                      <td className="px-4 py-2.5 text-on-surface-variant">{item.cif_nif || item.dni_nie || "—"}</td>
                      <td className="px-4 py-2.5 text-xs text-on-surface-variant">{item.telefono || item.email || "—"}</td>
                      <td className="px-4 py-2.5 text-on-surface">{item.deuda_pendiente_eur ? formatCurrency(item.deuda_pendiente_eur) : "—"}</td>
                      <td className="px-4 py-2.5">
                        <EstadoChip dominio="estado_cliente" valor={item.estado_cliente} />
                      </td>
                      <td className="px-4 py-2.5 text-on-surface-variant">{item.sector || "—"}</td>
                      <td className="px-4 py-2.5">
                        <Link href={`/clientes/${item.id}`} className="text-xs font-medium text-primary hover:underline">
                          Ver ficha
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="px-4 pb-4">
              <Pagination page={data.page} pages={data.pages} total={data.total} onChange={setPage} />
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
