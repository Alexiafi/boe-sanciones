"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { EnriquecimientoIntento, Sancionado, Seguimiento } from "@/lib/types";
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
  LinkButton,
  Notice,
  Select,
  Spinner,
} from "@/components/ui";
import { enlaceExterno, formatCurrency, formatDate, formatDateTime } from "@/lib/formatters";

const states = ["nueva", "revisada", "contactada", "descartada"] as const;

export default function SancionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [sancion, setSancion] = useState<Sancionado | null>(null);
  const [seguimientos, setSeguimientos] = useState<Seguimiento[]>([]);
  const [intentos, setIntentos] = useState<EnriquecimientoIntento[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [estado, setEstado] = useState("nueva");
  const [nombre, setNombre] = useState("");
  const [identificador, setIdentificador] = useState("");
  const [tipoIdentificador, setTipoIdentificador] = useState("");
  const [direccion, setDireccion] = useState("");
  const [localidad, setLocalidad] = useState("");
  const [provincia, setProvincia] = useState("");
  const [codigoPostal, setCodigoPostal] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [web, setWeb] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [telefonoSecundario, setTelefonoSecundario] = useState("");
  const [facebookUrl, setFacebookUrl] = useState("");
  const [instagramUrl, setInstagramUrl] = useState("");
  const [twitterUrl, setTwitterUrl] = useState("");
  const [nota, setNota] = useState("");
  const [notaError, setNotaError] = useState<string | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [enrichNotice, setEnrichNotice] = useState<string | null>(null);
  const [converting, setConverting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const result = (await api.sanciones.get(Number(id))) as unknown as Sancionado;
      setSancion(result);
      setSeguimientos(result.seguimientos || []);
      setEstado(result.estado_oportunidad);
      setNombre(result.nombre || "");
      setIdentificador(result.identificador || "");
      setTipoIdentificador(result.tipo_identificador || "");
      setDireccion(result.direccion || "");
      setLocalidad(result.localidad || "");
      setProvincia(result.provincia || "");
      setCodigoPostal(result.codigo_postal || "");
      setTelefono(result.telefono || "");
      setEmail(result.email || "");
      setWeb(result.web || "");
      setLinkedinUrl(result.linkedin_url || "");
      setTelefonoSecundario(result.telefono_secundario || "");
      setFacebookUrl(result.facebook_url || "");
      setInstagramUrl(result.instagram_url || "");
      setTwitterUrl(result.twitter_url || "");
      setIntentos((await api.sanciones.enrichmentAttempts(Number(id))) as unknown as EnriquecimientoIntento[]);
    } catch {
      setSancion(null);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  const saveOpportunity = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      const result = (await api.sanciones.update(Number(id), {
        estado_oportunidad: estado,
        nombre: nombre || null,
        identificador: identificador || null,
        tipo_identificador: tipoIdentificador || null,
        direccion: direccion || null,
        localidad: localidad || null,
        provincia: provincia || null,
        codigo_postal: codigoPostal || null,
        telefono: telefono || null,
        email: email || null,
        web: web || null,
        linkedin_url: linkedinUrl || null,
        telefono_secundario: telefonoSecundario || null,
        facebook_url: facebookUrl || null,
        instagram_url: instagramUrl || null,
        twitter_url: twitterUrl || null,
      })) as unknown as Sancionado;
      setSancion(result);
      setSeguimientos(result.seguimientos || []);
      setNotice(
        "Cambios guardados. Lo que has modificado se comparte con el resto de avisos de este mismo DNI/CIF y con su ficha de cliente."
      );
    } catch (error) {
      setNotice(`No se pudieron guardar los cambios: ${error}`);
    } finally {
      setSaving(false);
    }
  };

  const addSeguimiento = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!nota.trim()) return;
    setNotaError(null);
    try {
      await api.sanciones.addSeguimiento(Number(id), { nota, estado: "pendiente" });
      setNota("");
      setSeguimientos((await api.sanciones.getSeguimientos(Number(id))) as unknown as Seguimiento[]);
    } catch (error) {
      setNotaError(`No se pudo guardar la nota: ${error}`);
    }
  };

  const enrichContact = async () => {
    setEnriching(true);
    setEnrichNotice(null);
    try {
      const result = await api.sanciones.enrich(Number(id));
      // Reaching for this button marks the lead as "revisada" server-side
      // (see POST /enriquecer); reflect that immediately instead of waiting
      // for a manual reload.
      setEstado(result.estado_oportunidad);
      setSancion((prev) => (prev ? { ...prev, estado_oportunidad: result.estado_oportunidad } : prev));
      setEnrichNotice("Enriquecimiento encolado. Los resultados tardan unos segundos en aparecer; recarga para verlos.");
    } catch (error) {
      setEnrichNotice(`No se pudo lanzar el enriquecimiento: ${error}`);
    } finally {
      setEnriching(false);
    }
  };

  const convertToClient = async () => {
    setConverting(true);
    try {
      const result = await api.sanciones.convertir(Number(id));
      router.push(`/clientes/${(result.cliente as { id: number }).id}`);
    } catch (error) {
      setNotice(`No se pudo convertir en cliente: ${error}`);
      setConverting(false);
    }
  };

  if (loading) return <Spinner />;
  if (loadError || !sancion) {
    return <ErrorState message="Oportunidad no encontrada o no se pudo cargar." onRetry={load} />;
  }
  const amount = sancion.importe_multa_eur ?? sancion.importe_deuda_eur;

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <Link href="/sanciones" className="text-sm text-primary hover:underline">
          ← Panel de Multas
        </Link>
        <span className="text-on-surface-variant">/</span>
        <h1 className="truncate text-xl font-bold text-on-surface">
          {sancion.codigo} · {sancion.nombre_mostrado || sancion.nombre || sancion.identificador || "Sin identificar"}
        </h1>
      </div>
      <IdentidadBanner sancion={sancion} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardTitle>Datos extraídos</CardTitle>
            <div className="mt-2 divide-y divide-outline-variant/15">
              <InfoRow label="Nombre" value={sancion.nombre} />
              <InfoRow label="Tipo de persona" value={sancion.tipo_persona} />
              <InfoRow label="Identificador" value={sancion.identificador} />
              <InfoRow label="Dirección" value={sancion.direccion} />
              <InfoRow label="Localidad" value={sancion.localidad} />
              <InfoRow label="Provincia" value={sancion.provincia} />
              <InfoRow label="Código postal" value={sancion.codigo_postal} />
              <InfoRow label="Matrícula" value={sancion.matricula_coche} />
            </div>
          </Card>

          <Card>
            <CardTitle>Expediente</CardTitle>
            <div className="mt-2 divide-y divide-outline-variant/15">
              <InfoRow label="Materia" value={sancion.dominio_material} />
              <InfoRow label="Procedimiento" value={sancion.tipo_procedimiento} />
              <InfoRow label="Organismo" value={sancion.organismo_emisor} />
              <InfoRow label="Expediente" value={sancion.expediente} />
              <InfoRow label="Cuantía" value={amount == null ? null : formatCurrency(amount)} />
              <InfoRow label="Fecha de resolución" value={formatDate(sancion.fecha_resolucion)} />
              <InfoRow label="Plazo de pago voluntario" value={sancion.plazo_pago_voluntario} />
              <InfoRow label="Motivo" value={sancion.razon_sancion} />
              <InfoRow label="Observaciones" value={sancion.observaciones} />
            </div>
          </Card>

          <Card>
            <CardHeaderWithChip sancion={sancion} />
            {sancion.contacto_estado === "sin_datos" && (
              <Notice tone="info" className="mb-3">
                No hay nombre ni identificador fiscal suficientes para buscar contacto
                automáticamente. Completa el CIF/DNI a mano y vuelve a enriquecer.
              </Notice>
            )}
            {intentos[0]?.resultado === "error" && intentos[0].error && (
              <Notice tone="danger" className="mb-3">
                {intentos[0].error}
              </Notice>
            )}
            <div className="mt-2 divide-y divide-outline-variant/15">
              <ContactoRow label="Teléfono" valor={sancion.telefono} dato={sancion.contacto_detalle?.telefono} />
              <ContactoRow label="Teléfono secundario" valor={sancion.telefono_secundario} dato={sancion.contacto_detalle?.telefono_secundario} />
              <ContactoRow label="Email" valor={sancion.email} dato={sancion.contacto_detalle?.email} />
              <ContactoRow label="Web" valor={sancion.web} dato={sancion.contacto_detalle?.web} />
              <ContactoRow label="LinkedIn" valor={sancion.linkedin_url} dato={sancion.contacto_detalle?.linkedin_url} />
              <ContactoRow label="Facebook" valor={sancion.facebook_url} dato={sancion.contacto_detalle?.facebook_url} />
              <ContactoRow label="Instagram" valor={sancion.instagram_url} dato={sancion.contacto_detalle?.instagram_url} />
              <ContactoRow label="Twitter / X" valor={sancion.twitter_url} dato={sancion.contacto_detalle?.twitter_url} />
            </div>
            {sancion.contacto_estado !== "pendiente" && (
              <div className="mt-3 space-y-1 text-xs text-on-surface-variant">
                {sancion.contacto_fuente && (
                  <p>
                    Fuente: {etiquetaFuente(sancion.contacto_fuente)}
                    {sancion.contacto_confidence != null && ` · confianza ${(sancion.contacto_confidence * 100).toFixed(0)}%`}
                  </p>
                )}
                {enlaceExterno(sancion.contacto_url) && (
                  <p>
                    Origen:{" "}
                    <a href={enlaceExterno(sancion.contacto_url)!} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                      {sancion.contacto_url}
                    </a>
                  </p>
                )}
                {sancion.contacto_actualizado_at && <p>Actualizado: {formatDateTime(sancion.contacto_actualizado_at)}</p>}
              </div>
            )}
            <div className="mt-4">
              <Button onClick={enrichContact} disabled={enriching} size="sm">
                {enriching ? "Encolando…" : "Enriquecer contacto"}
              </Button>
            </div>
            {enrichNotice && (
              <Notice tone="info" className="mt-3">
                {enrichNotice}
              </Notice>
            )}
            {intentos.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">Historial de intentos</p>
                {intentos.map((intento) => (
                  <div key={intento.id} className="rounded-lg bg-surface-container-low p-3 text-xs">
                    <span className="font-medium text-on-surface">{intento.resultado}</span>
                    <span className="text-on-surface-variant"> · {intento.proveedor} · {formatDateTime(intento.created_at)}</span>
                    {intento.evidencia && <p className="mt-1 text-on-surface-variant">{intento.evidencia}</p>}
                    {intento.error && <p className="mt-1 text-error">{intento.error}</p>}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <HistorialDelTitular sancion={sancion} />

          <Card>
            <CardTitle>Seguimiento</CardTitle>
            <form onSubmit={addSeguimiento} className="mt-4 mb-4 flex gap-3">
              <Input value={nota} onChange={(event) => setNota(event.target.value)} placeholder="Añadir nota" className="flex-1" />
              <Button type="submit" size="sm">
                Guardar nota
              </Button>
            </form>
            {notaError && (
              <Notice tone="danger" className="mb-4">
                {notaError}
              </Notice>
            )}
            {seguimientos.length ? (
              <div className="space-y-2">
                {seguimientos.map((item) => (
                  <div key={item.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
                    <span className="text-xs text-on-surface-variant">{formatDateTime(item.created_at)}</span>
                    <p className="text-on-surface">{item.nota || "Sin nota"}</p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="Sin seguimientos todavía." />
            )}
          </Card>
        </div>

        <aside className="space-y-6">
          <Card>
            <CardTitle>Editar oportunidad</CardTitle>
            <form onSubmit={saveOpportunity} className="mt-4 space-y-3">
              <Field label="Nombre / razón social">
                <Input value={nombre} onChange={(event) => setNombre(event.target.value)} maxLength={300} />
              </Field>
              <Field label="Tipo de identificador">
                <Select value={tipoIdentificador} onChange={(event) => setTipoIdentificador(event.target.value)}>
                  <option value="">Sin especificar</option>
                  <option value="CIF">CIF (empresa)</option>
                  <option value="NIF">NIF</option>
                  <option value="DNI">DNI</option>
                  <option value="NIE">NIE</option>
                </Select>
              </Field>
              <Field label="CIF / DNI">
                <Input
                  value={identificador}
                  onChange={(event) => setIdentificador(event.target.value)}
                  maxLength={50}
                  placeholder="B12345678 o 12345678Z"
                />
              </Field>
              <Field label="Dirección">
                <Input value={direccion} onChange={(event) => setDireccion(event.target.value)} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Localidad">
                  <Input value={localidad} onChange={(event) => setLocalidad(event.target.value)} maxLength={200} />
                </Field>
                <Field label="C. postal">
                  <Input value={codigoPostal} onChange={(event) => setCodigoPostal(event.target.value)} maxLength={10} />
                </Field>
              </div>
              <Field label="Provincia">
                <Input value={provincia} onChange={(event) => setProvincia(event.target.value)} maxLength={200} />
              </Field>
              <Field label="Estado">
                <Select value={estado} onChange={(event) => setEstado(event.target.value)}>
                  {states.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                  {/* Set by converting to a client, never by hand: shown so the form does not silently change it. */}
                  {sancion.estado_oportunidad === "cliente" && <option value="cliente">cliente (asignado)</option>}
                </Select>
              </Field>
              <Field label="Teléfono">
                <Input value={telefono} onChange={(event) => setTelefono(event.target.value)} maxLength={50} />
              </Field>
              <Field label="Teléfono secundario">
                <Input value={telefonoSecundario} onChange={(event) => setTelefonoSecundario(event.target.value)} maxLength={50} />
              </Field>
              <Field label="Email">
                <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={200} />
              </Field>
              <Field label="Web">
                <Input value={web} onChange={(event) => setWeb(event.target.value)} maxLength={500} placeholder="https://…" />
              </Field>
              <Field label="LinkedIn (enlace añadido a mano)">
                <Input value={linkedinUrl} onChange={(event) => setLinkedinUrl(event.target.value)} maxLength={500} placeholder="https://linkedin.com/…" />
              </Field>
              <Field label="Facebook">
                <Input value={facebookUrl} onChange={(event) => setFacebookUrl(event.target.value)} maxLength={500} placeholder="https://facebook.com/…" />
              </Field>
              <Field label="Instagram">
                <Input value={instagramUrl} onChange={(event) => setInstagramUrl(event.target.value)} maxLength={500} placeholder="https://instagram.com/…" />
              </Field>
              <Field label="Twitter / X">
                <Input value={twitterUrl} onChange={(event) => setTwitterUrl(event.target.value)} maxLength={500} placeholder="https://x.com/…" />
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
            <CardTitle>Conversión</CardTitle>
            <div className="mt-4">
              {sancion.cliente_id ? (
                <LinkButton href={`/clientes/${sancion.cliente_id}`} variant="secondary" className="w-full">
                  Ver ficha de cliente →
                </LinkButton>
              ) : (
                <Button onClick={convertToClient} disabled={converting} className="w-full">
                  {converting ? "Convirtiendo…" : "Convertir en cliente"}
                </Button>
              )}
            </div>
          </Card>

          <Card>
            <CardTitle>Documento BOE</CardTitle>
            <div className="mt-2 divide-y divide-outline-variant/15">
              <InfoRow label="BOE" value={sancion.boe_id} />
              <InfoRow label="Publicación" value={formatDate(sancion.fecha_publicacion)} />
            </div>
            {sancion.titulo_documento && <p className="mt-3 text-xs text-on-surface-variant">{sancion.titulo_documento}</p>}
            {sancion.url_documento && (
              <a
                href={sancion.url_documento}
                target="_blank"
                rel="noopener noreferrer"
                className="gradient-primary mt-3 inline-block rounded-lg px-4 py-2.5 text-sm text-on-primary shadow-ambient"
              >
                Ver documento oficial →
              </a>
            )}
            {sancion.tiene_copia_local && (
              <a
                href={api.documentos.archivoUrl(sancion.boe_document_id)}
                target="_blank"
                rel="noopener noreferrer"
                title="Copia guardada en nuestra base de datos; disponible aunque el BOE haya retirado el original"
                className="ml-2 mt-3 inline-block rounded-lg border border-outline-variant bg-white px-4 py-2.5 text-sm font-semibold text-primary shadow-sm hover:border-secondary hover:bg-surface-bright"
              >
                Ver copia archivada
              </a>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}

function CardHeaderWithChip({ sancion }: { sancion: Sancionado }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <CardTitle>Contacto</CardTitle>
      <EstadoChip dominio="contacto_estado" valor={sancion.contacto_estado} />
    </div>
  );
}

type ContactoDato = { valor: string; fuente_url: string | null; confidence: number };

function ContactoRow({ label, valor, dato }: { label: string; valor: string | null; dato?: ContactoDato }) {
  if (!valor) return null;
  const isUrl = /^https?:\/\//.test(valor);
  return (
    <div className="flex justify-between gap-4 py-3">
      <span className="text-[11px] font-semibold uppercase tracking-[0.055em] text-on-surface-variant">{label}</span>
      <span className="max-w-[62%] text-right text-sm font-semibold text-primary">
        {isUrl ? (
          <a href={valor} target="_blank" rel="noopener noreferrer" className="break-all hover:underline">
            {valor}
          </a>
        ) : (
          valor
        )}
        {enlaceExterno(dato?.fuente_url) && (
          <a
            href={enlaceExterno(dato?.fuente_url)!}
            target="_blank"
            rel="noopener noreferrer"
            title={`Fuente: ${dato?.fuente_url}`}
            className="ml-2 text-[10px] font-normal uppercase tracking-[0.05em] text-on-surface-variant hover:text-primary hover:underline"
          >
            fuente
          </a>
        )}
      </span>
    </div>
  );
}

const FUENTES: Record<string, string> = {
  manual: "Introducido a mano",
  sancionado: "Otro aviso del mismo DNI/CIF",
  cliente: "Ficha de cliente",
};

function etiquetaFuente(fuente: string): string {
  return FUENTES[fuente] ?? fuente;
}

function IdentidadBanner({ sancion }: { sancion: Sancionado }) {
  if (!sancion.cliente_id && !sancion.ya_contactado && sancion.otras_notificaciones === 0) return null;
  return (
    <div className="mb-6 space-y-2">
      {sancion.cliente_id && (
        <Notice tone="success">
          <span className="font-semibold">Ya es cliente{sancion.cliente_estado === "informado" ? " (solo información)" : ""}:</span>{" "}
          {sancion.cliente_nombre || sancion.nombre_mostrado}.{" "}
          <Link href={`/clientes/${sancion.cliente_id}`} className="font-semibold underline">
            Abrir su ficha →
          </Link>
        </Notice>
      )}
      {sancion.ya_contactado && (
        <Notice tone="warning">
          <span className="font-semibold">Ya se contactó con esta persona</span>
          {sancion.ultima_gestion ? ` (última gestión ${formatDate(sancion.ultima_gestion)})` : ""} a través de otro aviso del mismo DNI/CIF.
          Revisa abajo las notas antes de volver a llamar.
        </Notice>
      )}
      {sancion.otras_notificaciones > 0 && !sancion.ya_contactado && (
        <Notice tone="info">
          Este DNI/CIF tiene {sancion.otras_notificaciones} aviso{sancion.otras_notificaciones === 1 ? "" : "s"} más (ver «Mismo titular» abajo).
        </Notice>
      )}
    </div>
  );
}

function HistorialDelTitular({ sancion }: { sancion: Sancionado }) {
  const relacionadas = sancion.relacionadas ?? [];
  const notas = sancion.seguimientos_relacionados ?? [];
  if (relacionadas.length === 0 && notas.length === 0) return null;
  return (
    <Card>
      <CardTitle>Mismo titular · otros avisos</CardTitle>
      <p className="mt-1 text-xs text-on-surface-variant">
        Avisos con el mismo DNI/CIF. Los datos de contacto que añadas aquí o en ellos se comparten entre todos.
      </p>
      {relacionadas.length > 0 && (
        <div className="mt-4 space-y-2">
          {relacionadas.map((item) => (
            <div key={item.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Link href={`/sanciones/${item.id}`} className="font-mono text-xs font-medium text-primary hover:underline">
                    {item.codigo}
                  </Link>
                  <span className="text-xs text-on-surface-variant">{formatDate(item.fecha_publicacion)}</span>
                  {(item.importe_multa_eur ?? item.importe_deuda_eur) != null && (
                    <span className="text-xs text-on-surface">{formatCurrency(item.importe_multa_eur ?? item.importe_deuda_eur)}</span>
                  )}
                </div>
                <EstadoChip dominio="estado_oportunidad" valor={item.estado_oportunidad} />
              </div>
              {item.organismo_emisor && <p className="mt-1 text-xs text-on-surface-variant">{item.organismo_emisor}</p>}
              {item.ultima_nota && <p className="mt-1 text-xs text-on-surface">«{item.ultima_nota}»</p>}
            </div>
          ))}
        </div>
      )}
      {notas.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">Notas escritas en esos avisos</p>
          <div className="space-y-2">
            {notas.map((nota) => (
              <div key={nota.id} className="rounded-lg bg-surface-container-low p-3 text-sm">
                <span className="text-xs text-on-surface-variant">
                  {formatDateTime(nota.created_at)} ·{" "}
                  <Link href={`/sanciones/${nota.sancionado_id}`} className="hover:underline">
                    {nota.codigo}
                  </Link>
                </span>
                <p className="text-on-surface">{nota.nota || "Sin nota"}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
