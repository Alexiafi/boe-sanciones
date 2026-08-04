"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { VinculoCliente } from "@/lib/types";
import { Button, Card, CardTitle, ConfirmDialog, EmptyState, Field, Input, Notice, Select, Spinner } from "@/components/ui";

export function VinculosBlock({ clienteId }: { clienteId: number }) {
  const [vinculos, setVinculos] = useState<VinculoCliente[]>([]);
  const [loading, setLoading] = useState(true);

  const [rol, setRol] = useState("");
  const [nombre, setNombre] = useState("");
  const [tipoPersona, setTipoPersona] = useState<"" | "fisica" | "juridica">("");
  const [identificador, setIdentificador] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [borrando, setBorrando] = useState<VinculoCliente | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const items = (await api.clientes.listVinculos(clienteId)) as unknown as VinculoCliente[];
      setVinculos(items);
    } catch {
      setVinculos([]);
    } finally {
      setLoading(false);
    }
  }, [clienteId]);

  useEffect(() => {
    load();
  }, [load]);

  const limpiarFormulario = () => {
    setRol("");
    setNombre("");
    setTipoPersona("");
    setIdentificador("");
    setTelefono("");
    setEmail("");
  };

  const addVinculo = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!rol.trim() || !nombre.trim()) return;
    setGuardando(true);
    setError(null);
    try {
      await api.clientes.addVinculo(clienteId, {
        rol: rol.trim(),
        nombre: nombre.trim(),
        tipo_persona: tipoPersona || null,
        identificador: identificador.trim() || null,
        telefono: telefono.trim() || null,
        email: email.trim() || null,
      });
      limpiarFormulario();
      await load();
    } catch (err) {
      setError(`No se pudo guardar el vínculo: ${err}`);
    } finally {
      setGuardando(false);
    }
  };

  const confirmarBorrado = async () => {
    if (!borrando) return;
    try {
      await api.clientes.deleteVinculo(clienteId, borrando.id);
      setBorrando(null);
      await load();
    } catch (err) {
      setError(`No se pudo eliminar el vínculo: ${err}`);
      setBorrando(null);
    }
  };

  return (
    <Card>
      <CardTitle>Vínculos (administrador, conductor, filial…)</CardTitle>
      <p className="mt-1 text-xs text-on-surface-variant">
        Personas o empresas relacionadas con este cliente cuyas sanciones también quieres seguir.
      </p>

      <form onSubmit={addVinculo} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Rol">
          <Input value={rol} onChange={(event) => setRol(event.target.value)} placeholder="p. ej. Administrador" maxLength={100} />
        </Field>
        <Field label="Nombre">
          <Input value={nombre} onChange={(event) => setNombre(event.target.value)} maxLength={500} />
        </Field>
        <Field label="Tipo de persona">
          <Select value={tipoPersona} onChange={(event) => setTipoPersona(event.target.value as typeof tipoPersona)}>
            <option value="">—</option>
            <option value="fisica">Física</option>
            <option value="juridica">Jurídica</option>
          </Select>
        </Field>
        <Field label="Identificador (NIF/NIE/CIF)">
          <Input value={identificador} onChange={(event) => setIdentificador(event.target.value)} maxLength={50} />
        </Field>
        <Field label="Teléfono">
          <Input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} />
        </Field>
        <Field label="Email">
          <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} />
        </Field>
        <div className="sm:col-span-2 lg:col-span-3">
          <Button type="submit" size="sm" disabled={guardando || !rol.trim() || !nombre.trim()}>
            {guardando ? "Guardando…" : "Añadir vínculo"}
          </Button>
        </div>
      </form>

      {error && (
        <Notice tone="danger" className="mt-4">
          {error}
        </Notice>
      )}

      <div className="mt-5">
        {loading && <Spinner />}
        {!loading && vinculos.length === 0 && (
          <EmptyState title="Sin vínculos todavía." description="Añade al administrador, un conductor u otra empresa del grupo." />
        )}
        {!loading && vinculos.length > 0 && (
          <div className="space-y-2">
            {vinculos.map((vinculo) => (
              <div key={vinculo.id} className="flex items-center justify-between gap-3 rounded-lg bg-surface-container-low p-3 text-sm">
                <div className="min-w-0">
                  <p className="font-medium text-on-surface">
                    {vinculo.nombre || "Sin nombre"} <span className="text-xs font-normal text-on-surface-variant">· {vinculo.rol}</span>
                  </p>
                  <p className="text-xs text-on-surface-variant">
                    {[vinculo.identificador, vinculo.telefono, vinculo.email].filter(Boolean).join(" · ") || "Sin datos de contacto"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  {vinculo.cliente_vinculado_id && (
                    <Link href={`/clientes/${vinculo.cliente_vinculado_id}`} className="text-xs font-medium text-primary hover:underline">
                      Ver ficha
                    </Link>
                  )}
                  <button onClick={() => setBorrando(vinculo)} className="text-xs text-on-surface-variant hover:text-error">
                    Eliminar
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={borrando !== null}
        onOpenChange={(open) => !open && setBorrando(null)}
        title="Eliminar vínculo"
        description={borrando ? `Se eliminará "${borrando.nombre || borrando.rol}". Las sanciones ya asignadas quedarán sin titular específico.` : undefined}
        confirmLabel="Eliminar"
        onConfirm={confirmarBorrado}
        danger
      />
    </Card>
  );
}
