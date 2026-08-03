"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { PaginatedResponse, Sancionado } from "@/lib/types";
import {
  Card,
  EmptyState,
  ErrorState,
  EstadoChip,
  Field,
  Input,
  PageHeader,
  Pagination,
  Select,
  Spinner,
} from "@/components/ui";
import { formatCurrency, formatDate } from "@/lib/formatters";

function dateInput(daysAgo: number) {
  const value = new Date();
  value.setDate(value.getDate() - daysAgo);
  return value.toISOString().slice(0, 10);
}

const ESTADOS = ["nueva", "revisada", "contactada", "descartada", "cliente"];

export default function SancionesPage() {
  const [data, setData] = useState<PaginatedResponse<Sancionado> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
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
    setError(false);
    try {
      const params: Record<string, string> = {
        page: String(page), page_size: "20", fecha_desde: fechaDesde, fecha_hasta: fechaHasta,
      };
      if (search) params.search = search;
      if (estado) params.estado_oportunidad = estado;
      if (materia) params.materia = materia;
      if (persona) params.tipo_persona = persona;
      if (contacto) params.solo_con_contacto = contacto;
      if (cuantiaMin) params.cuantia_min = cuantiaMin;
      if (cuantiaMax) params.cuantia_max = cuantiaMax;
      setData((await api.sanciones.list(params)) as unknown as PaginatedResponse<Sancionado>);
    } catch {
      setError(true);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [page, search, estado, materia, persona, contacto, cuantiaMin, cuantiaMax, fechaDesde, fechaHasta]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const resetPage = () => setPage(1);

  return (
    <div>
      <PageHeader
        title="Panel de Multas"
        description="Publicaciones BOE de los últimos 30 días. Consultar esta lista no inicia scraping."
      />

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
            <Input
              placeholder="Código, nombre, identificador o expediente"
              value={search}
              onChange={(event) => { setSearch(event.target.value); resetPage(); }}
            />
          </Field>
          <Field label="Estado">
            <Select value={estado} onChange={(event) => { setEstado(event.target.value); resetPage(); }}>
              <option value="">Todos los estados</option>
              {ESTADOS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Materia">
            <Input placeholder="Texto libre" value={materia} onChange={(event) => { setMateria(event.target.value); resetPage(); }} />
          </Field>
          <Field label="Persona">
            <Select value={persona} onChange={(event) => { setPersona(event.target.value); resetPage(); }}>
              <option value="">Física o jurídica</option>
              <option value="fisica">Física</option>
              <option value="juridica">Jurídica</option>
            </Select>
          </Field>
          <Field label="Publicada desde">
            <Input type="date" value={fechaDesde} onChange={(event) => { setFechaDesde(event.target.value); resetPage(); }} />
          </Field>
          <Field label="Publicada hasta">
            <Input type="date" value={fechaHasta} onChange={(event) => { setFechaHasta(event.target.value); resetPage(); }} />
          </Field>
          <Field label="Cuantía mínima">
            <Input type="number" min="0" value={cuantiaMin} onChange={(event) => { setCuantiaMin(event.target.value); resetPage(); }} />
          </Field>
          <Field label="Cuantía máxima">
            <Input type="number" min="0" value={cuantiaMax} onChange={(event) => { setCuantiaMax(event.target.value); resetPage(); }} />
          </Field>
          <Field label="Contacto">
            <Select value={contacto} onChange={(event) => { setContacto(event.target.value); resetPage(); }}>
              <option value="">Todo contacto</option>
              <option value="true">Con contacto</option>
              <option value="false">Sin contacto</option>
            </Select>
          </Field>
          <div className="flex items-end">
            <button
              type="submit"
              className="gradient-primary w-full rounded-lg px-4 py-2.5 text-sm font-medium text-on-primary shadow-ambient"
            >
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
            <EmptyState title="No se encontraron oportunidades." description="Prueba a ampliar el rango de fechas o quitar filtros." />
          </div>
        )}
        {!loading && !error && !!data?.items.length && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-container-low">
                  <tr>
                    {["Código", "Nombre / razón social", "Identificador", "Materia", "Cuantía", "Estado", "Contacto", "Fecha", "BOE", ""].map((title) => (
                      <th key={title} scope="col" className="px-4 py-3 text-left font-medium text-on-surface-variant">
                        {title}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => {
                    const amount = item.importe_multa_eur ?? item.importe_deuda_eur;
                    return (
                      <tr key={item.id} className="hover:bg-surface-container-low">
                        <td className="px-4 py-2.5 font-mono text-xs text-on-surface-variant">{item.codigo}</td>
                        <td className="max-w-[180px] truncate px-4 py-2.5 font-medium text-on-surface">{item.nombre || "—"}</td>
                        <td className="px-4 py-2.5 text-on-surface-variant">{item.identificador || "—"}</td>
                        <td className="px-4 py-2.5 text-on-surface">{item.dominio_material || "—"}</td>
                        <td className="px-4 py-2.5 text-on-surface">{formatCurrency(amount)}</td>
                        <td className="px-4 py-2.5">
                          <EstadoChip dominio="estado_oportunidad" valor={item.estado_oportunidad} />
                        </td>
                        <td className="px-4 py-2.5 text-xs text-on-surface-variant">{item.telefono || item.email || "—"}</td>
                        <td className="px-4 py-2.5 text-on-surface-variant">{formatDate(item.fecha_publicacion)}</td>
                        <td className="px-4 py-2.5">
                          {item.url_documento ? (
                            <a href={item.url_documento} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                              Ver BOE
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          <Link href={`/sanciones/${item.id}`} className="text-xs font-medium text-primary hover:underline">
                            Detalle
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
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
