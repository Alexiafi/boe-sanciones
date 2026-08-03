"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { AccionAgendada, ClienteDetail } from "@/lib/types";
import {
  Button,
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  EstadoChip,
  Field,
  Input,
  InfoRow,
  Notice,
  Select,
  Spinner,
} from "@/components/ui";
import { formatCurrency, formatDateTime } from "@/lib/formatters";
import { DocumentosBlock } from "./DocumentosBlock";
import { HistoricoBlock } from "./HistoricoBlock";

export default function ClienteDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [cliente, setCliente] = useState<ClienteDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [estadoCliente, setEstadoCliente] = useState("activo");
  const [personaContacto, setPersonaContacto] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [web, setWeb] = useState("");
  const [sector, setSector] = useState("");

  const [nota, setNota] = useState("");
  const [notaError, setNotaError] = useState<string | null>(null);
  const [accionTitulo, setAccionTitulo] = useState("");
  const [accionTipo, setAccionTipo] = useState<"llamada" | "email" | "tarea">("llamada");
  const [accionError, setAccionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const result = (await api.clientes.get(Number(id))) as unknown as ClienteDetail;
      setCliente(result);
      setEstadoCliente(result.estado_cliente);
      setPersonaContacto(result.persona_contacto || "");
      setTelefono(result.telefono || "");
      setEmail(result.email || "");
      setWeb(result.web || "");
      setSector(result.sector || "");
    } catch {
      setCliente(null);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  const saveCliente = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setNotice(null);
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
    } catch (error) {
      setNotice(`No se pudieron guardar los cambios: ${error}`);
    } finally {
      setSaving(false);
    }
  };

  const addNota = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!nota.trim()) return;
    setNotaError(null);
    try {
      await api.clientes.addNota(Number(id), { texto: nota });
      setNota("");
      await load();
    } catch (error) {
      setNotaError(`No se pudo guardar la nota: ${error}`);
    }
  };

  const addAccion = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!accionTitulo.trim()) return;
    setAccionError(null);
    try {
      await api.clientes.addAccion(Number(id), { tipo: accionTipo, titulo: accionTitulo });
      setAccionTitulo("");
      await load();
    } catch (error) {
      setAccionError(`No se pudo agendar la acción: ${error}`);
    }
  };

  const marcarAccion = async (accion: AccionAgendada, estado: "hecha" | "cancelada") => {
    try {
      await api.clientes.updateAccion(Number(id), accion.id, { estado });
      await load();
    } catch (error) {
      setAccionError(`No se pudo actualizar la acción: ${error}`);
    }
  };

  if (loading) return <Spinner />;
  if (loadError || !cliente) {
    return <ErrorState message="Cliente no encontrado o no se pudo cargar." onRetry={load} />;
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Link href="/clientes" className="text-sm text-primary hover:underline">
          ← Clientes
        </Link>
        <span className="text-on-surface-variant">/</span>
        <h1 className="truncate text-xl font-bold text-on-surface">
          {cliente.codigo} · {cliente.nombre_razon_social}
        </h1>
        <EstadoChip dominio="estado_cliente" valor={cliente.estado_cliente} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardTitle>Datos del cliente</CardTitle>
            <div className="mt-2 divide-y divide-outline-variant/15">
              <InfoRow label="Tipo de persona" value={cliente.tipo_persona} />
              <InfoRow label="CIF/NIF" value={cliente.cif_nif} />
              <InfoRow label="DNI/NIE" value={cliente.dni_nie} />
              <InfoRow label="Matrículas" value={cliente.matriculas?.length ? cliente.matriculas.join(", ") : null} />
              <InfoRow label="Dirección fiscal" value={cliente.direccion_fiscal} />
              <InfoRow label="Localidad" value={cliente.localidad} />
              <InfoRow label="Provincia" value={cliente.provincia} />
              <InfoRow label="Deuda pendiente" value={cliente.deuda_pendiente_eur ? formatCurrency(cliente.deuda_pendiente_eur) : null} />
              <InfoRow label="Fecha de contrato" value={cliente.fecha_contrato} />
              <InfoRow label="Precio de contrato" value={cliente.precio_contrato ? formatCurrency(cliente.precio_contrato) : null} />
            </div>
          </Card>

          <Card>
            <CardTitle>Sanciones vinculadas</CardTitle>
            <div className="mt-4">
              {cliente.sanciones.length ? (
                <div className="space-y-2">
                  {cliente.sanciones.map((item) => (
                    <div key={item.id} className="flex items-center justify-between rounded-lg bg-surface-container-low p-3 text-sm">
                      <div>
                        <span className="font-mono text-xs text-on-surface-variant">{item.codigo}</span>
                        <span className="ml-2 text-on-surface-variant">{item.fecha_publicacion}</span>
                        {(item.importe_multa_eur ?? item.importe_deuda_eur) != null && (
                          <span className="ml-2 text-on-surface">{formatCurrency(item.importe_multa_eur ?? item.importe_deuda_eur)}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        {item.url_documento && (
                          <a href={item.url_documento} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                            Ver BOE
                          </a>
                        )}
                        <Link href={`/sanciones/${item.id}`} className="text-xs text-primary hover:underline">
                          Detalle
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Sin sanciones vinculadas." />
              )}
            </div>
          </Card>

          <HistoricoBlock clienteId={cliente.id} />

          <DocumentosBlock cliente={cliente} />

          <Card>
            <CardTitle>Notas del cliente</CardTitle>
            <form onSubmit={addNota} className="mt-4 mb-4 flex gap-3">
              <Input value={nota} onChange={(event) => setNota(event.target.value)} placeholder="Añadir nota" className="flex-1" />
              <Button type="submit" size="sm">
                Guardar
              </Button>
            </form>
            {notaError && (
              <Notice tone="danger" className="mb-4">
                {notaError}
              </Notice>
            )}
            {cliente.notas.length ? (
              <div className="space-y-2">
                {cliente.notas.map((item) => (
                  <div key={item.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
                    <span className="text-xs text-on-surface-variant">
                      {formatDateTime(item.created_at)}
                      {item.autor ? ` · ${item.autor}` : ""}
                    </span>
                    <p className="text-on-surface">{item.texto}</p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="Sin notas todavía." />
            )}
          </Card>

          <Card>
            <CardTitle>Registro de actividad</CardTitle>
            <div className="mt-4">
              {cliente.actividades.length ? (
                <div className="space-y-2">
                  {cliente.actividades.map((item) => (
                    <div key={item.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
                      <span className="text-xs text-on-surface-variant">
                        {formatDateTime(item.created_at)} · {item.tipo}
                      </span>
                      <p className="font-medium text-on-surface">{item.titulo}</p>
                      {item.detalle && <p className="mt-1 text-xs text-on-surface-variant">{item.detalle}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Sin actividad registrada." />
              )}
            </div>
          </Card>
        </div>

        <aside className="space-y-6">
          <Card>
            <CardTitle>Editar cliente</CardTitle>
            <form onSubmit={saveCliente} className="mt-4 space-y-3">
              <Field label="Estado">
                <Select value={estadoCliente} onChange={(event) => setEstadoCliente(event.target.value)}>
                  <option value="activo">Activo</option>
                  <option value="inactivo">Inactivo</option>
                </Select>
              </Field>
              <Field label="Persona de contacto">
                <Input value={personaContacto} onChange={(event) => setPersonaContacto(event.target.value)} maxLength={200} />
              </Field>
              <Field label="Teléfono">
                <Input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} />
              </Field>
              <Field label="Email">
                <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} />
              </Field>
              <Field label="Web">
                <Input value={web} onChange={(event) => setWeb(event.target.value)} maxLength={500} placeholder="https://…" />
              </Field>
              <Field label="Sector">
                <Input value={sector} onChange={(event) => setSector(event.target.value)} maxLength={200} />
              </Field>
              <Button type="submit" disabled={saving} className="w-full">
                {saving ? "Guardando…" : "Guardar cambios"}
              </Button>
              {notice && (
                <Notice tone="info" className="mt-2">
                  {notice}
                </Notice>
              )}
            </form>
          </Card>

          <Card>
            <CardTitle>Acciones</CardTitle>
            <form onSubmit={addAccion} className="mt-4 space-y-2">
              <Field label="Tipo">
                <Select value={accionTipo} onChange={(event) => setAccionTipo(event.target.value as typeof accionTipo)}>
                  <option value="llamada">Llamada</option>
                  <option value="email">Email</option>
                  <option value="tarea">Tarea</option>
                </Select>
              </Field>
              <Field label="Título">
                <Input value={accionTitulo} onChange={(event) => setAccionTitulo(event.target.value)} placeholder="p. ej. Agendar llamada" />
              </Field>
              <Button type="submit" className="w-full">
                Agendar
              </Button>
            </form>
            {accionError && (
              <Notice tone="danger" className="mt-3">
                {accionError}
              </Notice>
            )}
            <div className="mt-4">
              {cliente.acciones.length ? (
                <div className="space-y-2">
                  {cliente.acciones.map((accion) => (
                    <div key={accion.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-on-surface">{accion.titulo}</span>
                        <EstadoChip dominio="accion_estado" valor={accion.estado} />
                      </div>
                      <p className="mt-1 text-xs text-on-surface-variant">
                        {accion.tipo} · {formatDateTime(accion.created_at)}
                      </p>
                      {accion.estado === "pendiente" && (
                        <div className="mt-2 flex gap-3">
                          <button onClick={() => marcarAccion(accion, "hecha")} className="text-xs text-primary hover:underline">
                            Marcar hecha
                          </button>
                          <button onClick={() => marcarAccion(accion, "cancelada")} className="text-xs text-on-surface-variant hover:underline">
                            Cancelar
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="Sin acciones agendadas." />
              )}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}
