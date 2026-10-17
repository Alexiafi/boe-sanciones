"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { Sancionado } from "@/lib/types";
import { Button, Card, CardTitle, Field, Input, Notice, PageHeader, Select, Spinner, Textarea } from "@/components/ui";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function NuevaMultaForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [nombre, setNombre] = useState("");
  const [tipoPersona, setTipoPersona] = useState("");
  const [identificador, setIdentificador] = useState("");
  const [tipoIdentificador, setTipoIdentificador] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [web, setWeb] = useState("");
  const [direccion, setDireccion] = useState("");
  const [localidad, setLocalidad] = useState("");
  const [provincia, setProvincia] = useState("");
  const [codigoPostal, setCodigoPostal] = useState("");
  const [matricula, setMatricula] = useState("");
  const [dominioMaterial, setDominioMaterial] = useState("");
  const [importe, setImporte] = useState("");
  const [expediente, setExpediente] = useState("");
  const [organismo, setOrganismo] = useState("");
  const [fechaPublicacion, setFechaPublicacion] = useState(todayIso);
  const [razon, setRazon] = useState("");
  const [crearCliente, setCrearCliente] = useState(searchParams.get("como_cliente") === "1");

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const result = (await api.sanciones.create({
        nombre: nombre || null,
        tipo_persona: tipoPersona || null,
        identificador: identificador || null,
        tipo_identificador: tipoIdentificador || null,
        telefono: telefono || null,
        email: email || null,
        web: web || null,
        direccion: direccion || null,
        localidad: localidad || null,
        provincia: provincia || null,
        codigo_postal: codigoPostal || null,
        matricula_coche: matricula || null,
        dominio_material: dominioMaterial || null,
        importe_multa_eur: importe ? Number(importe) : null,
        expediente: expediente || null,
        organismo_emisor: organismo || null,
        fecha_publicacion: fechaPublicacion || null,
        razon_sancion: razon || null,
        crear_cliente: crearCliente,
      })) as unknown as Sancionado;
      if (crearCliente && result.cliente_id) {
        router.push(`/clientes/${result.cliente_id}`);
      } else {
        router.push(`/sanciones/${result.id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el alta manual.");
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Nueva multa"
        description="Alta manual de una sanción que no entra por el BOE/TEU. Puedes registrarla también como cliente en el mismo paso."
      />

      <form onSubmit={onSubmit} className="space-y-6">
        <Card>
          <CardTitle>Persona o empresa</CardTitle>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Nombre / razón social">
              <Input value={nombre} onChange={(event) => setNombre(event.target.value)} maxLength={500} required={!identificador} />
            </Field>
            <Field label="Tipo de persona">
              <Select value={tipoPersona} onChange={(event) => setTipoPersona(event.target.value)}>
                <option value="">Sin especificar</option>
                <option value="fisica">Física</option>
                <option value="juridica">Jurídica</option>
              </Select>
            </Field>
            <Field label="CIF / NIF">
              <Input value={identificador} onChange={(event) => setIdentificador(event.target.value)} maxLength={50} required={!nombre} />
            </Field>
            <Field label="Tipo de identificador">
              <Select value={tipoIdentificador} onChange={(event) => setTipoIdentificador(event.target.value)}>
                <option value="">Sin especificar</option>
                <option value="CIF">CIF</option>
                <option value="NIF">NIF</option>
                <option value="NIE">NIE</option>
                <option value="DNI">DNI</option>
              </Select>
            </Field>
            <Field label="Teléfono" hint="Móvil 6/7 o fijo 8/9, 9 dígitos. Prefijo +34 opcional.">
              <Input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} placeholder="+34 612 345 678" />
            </Field>
            <Field label="Email">
              <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} />
            </Field>
            <Field label="Web">
              <Input value={web} onChange={(event) => setWeb(event.target.value)} maxLength={500} placeholder="https://…" />
            </Field>
            <Field label="Matrícula">
              <Input value={matricula} onChange={(event) => setMatricula(event.target.value)} maxLength={20} />
            </Field>
            <Field label="Dirección">
              <Input value={direccion} onChange={(event) => setDireccion(event.target.value)} />
            </Field>
            <Field label="Localidad">
              <Input value={localidad} onChange={(event) => setLocalidad(event.target.value)} maxLength={200} />
            </Field>
            <Field label="Provincia">
              <Input value={provincia} onChange={(event) => setProvincia(event.target.value)} maxLength={200} />
            </Field>
            <Field label="Código postal">
              <Input value={codigoPostal} onChange={(event) => setCodigoPostal(event.target.value)} maxLength={10} />
            </Field>
          </div>
        </Card>

        <Card>
          <CardTitle>Datos de la multa</CardTitle>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="Tipo / materia">
              <Input value={dominioMaterial} onChange={(event) => setDominioMaterial(event.target.value)} placeholder="Seguridad Social, Tráfico…" />
            </Field>
            <Field label="Cuantía (€)">
              <Input type="number" min="0" step="0.01" value={importe} onChange={(event) => setImporte(event.target.value)} />
            </Field>
            <Field label="Expediente">
              <Input value={expediente} onChange={(event) => setExpediente(event.target.value)} maxLength={200} />
            </Field>
            <Field label="Organismo emisor">
              <Input value={organismo} onChange={(event) => setOrganismo(event.target.value)} />
            </Field>
            <Field label="Fecha de publicación">
              <Input type="date" value={fechaPublicacion} onChange={(event) => setFechaPublicacion(event.target.value)} />
            </Field>
            <div className="md:col-span-2">
              <Field label="Motivo">
                <Textarea value={razon} onChange={(event) => setRazon(event.target.value)} rows={3} />
              </Field>
            </div>
          </div>
        </Card>

        <Card>
          <label className="flex items-start gap-3 text-sm text-on-surface">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-outline-variant"
              checked={crearCliente}
              onChange={(event) => setCrearCliente(event.target.checked)}
            />
            <span>
              <span className="font-semibold">Registrar también como cliente</span>
              <span className="mt-0.5 block text-xs text-on-surface-variant">
                Crea la ficha en el directorio y deja esta multa ya vinculada. Equivale a «Convertir en cliente».
              </span>
            </span>
          </label>
        </Card>

        {error && (
          <Notice tone="danger">{error}</Notice>
        )}

        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={saving}>
            {saving ? "Guardando…" : crearCliente ? "Guardar multa y cliente" : "Guardar multa"}
          </Button>
          <Button type="button" variant="secondary" onClick={() => router.push("/sanciones")} disabled={saving}>
            Cancelar
          </Button>
        </div>
      </form>
    </div>
  );
}

export default function NuevaMultaPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <NuevaMultaForm />
    </Suspense>
  );
}
