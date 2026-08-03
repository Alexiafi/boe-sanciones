"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Cliente, DocumentoComercial } from "@/lib/types";
import { Button, Card, CardTitle, EmptyState, EstadoChip, Field, Input, Notice, Spinner } from "@/components/ui";
import { formatDateTime } from "@/lib/formatters";

function ChecklistNotice({ faltantes }: { faltantes: { campo: string; mensaje: string }[] }) {
  if (faltantes.length === 0) return null;
  return (
    <Notice tone="warning" className="mt-2">
      <p className="mb-1 font-medium">Faltan datos para generar este documento:</p>
      <ul className="list-inside list-disc space-y-0.5">
        {faltantes.map((item) => (
          <li key={item.campo}>{item.mensaje}</li>
        ))}
      </ul>
    </Notice>
  );
}

export function DocumentosBlock({ cliente }: { cliente: Cliente }) {
  const clienteId = cliente.id;
  const [documentos, setDocumentos] = useState<DocumentoComercial[]>([]);
  const [loading, setLoading] = useState(true);

  const [faltantesContrato, setFaltantesContrato] = useState<{ campo: string; mensaje: string }[]>([]);
  const [faltantesFactura, setFaltantesFactura] = useState<{ campo: string; mensaje: string }[]>([]);
  const [precio, setPrecio] = useState("");
  const [cuantia, setCuantia] = useState("");
  const [concepto, setConcepto] = useState("");
  const [generando, setGenerando] = useState<"contrato" | "factura" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [enviando, setEnviando] = useState<number | null>(null);
  const [emailDestino, setEmailDestino] = useState(cliente.email || "");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [docs, validacionContrato, validacionFactura] = await Promise.all([
        api.clientes.listDocumentos(clienteId) as unknown as Promise<DocumentoComercial[]>,
        api.clientes.validarDocumento(clienteId, "contrato"),
        api.clientes.validarDocumento(clienteId, "factura"),
      ]);
      setDocumentos(docs);
      setFaltantesContrato(validacionContrato.faltantes);
      setFaltantesFactura(validacionFactura.faltantes);
    } catch {
      setDocumentos([]);
    } finally {
      setLoading(false);
    }
  }, [clienteId]);

  useEffect(() => {
    load();
  }, [load]);

  const generarContrato = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = Number(precio);
    if (!value || value <= 0) return;
    setGenerando("contrato");
    setNotice(null);
    try {
      await api.clientes.crearContrato(clienteId, value);
      setPrecio("");
      setNotice("Contrato generado. Recuerda que la plantilla puede seguir marcada como provisional.");
      await load();
    } catch (error) {
      setNotice(`No se pudo generar el contrato: ${error}`);
    } finally {
      setGenerando(null);
    }
  };

  const generarFactura = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = Number(cuantia);
    if (!value || value <= 0 || !concepto.trim()) return;
    setGenerando("factura");
    setNotice(null);
    try {
      await api.clientes.crearFactura(clienteId, value, concepto);
      setCuantia("");
      setConcepto("");
      setNotice("Factura generada.");
      await load();
    } catch (error) {
      setNotice(`No se pudo generar la factura: ${error}`);
    } finally {
      setGenerando(null);
    }
  };

  const enviar = async (documento: DocumentoComercial) => {
    setEnviando(documento.id);
    setNotice(null);
    try {
      await api.documentosComerciales.enviar(documento.id, emailDestino || null);
      setNotice("Documento enviado.");
      await load();
    } catch (error) {
      setNotice(
        `No se pudo enviar: ${error}. El envío de email está desactivado por defecto (EMAIL_SENDING_ENABLED=false) ` +
          "hasta que se configure un SMTP real o Mailpit para pruebas."
      );
    } finally {
      setEnviando(null);
    }
  };

  return (
    <Card>
      <CardTitle>Documentos</CardTitle>

      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">Contrato</p>
          <form onSubmit={generarContrato} className="flex items-end gap-2">
            <Field label="Precio (€)">
              <Input type="number" min="0" step="0.01" value={precio} onChange={(event) => setPrecio(event.target.value)} />
            </Field>
            <Button type="submit" size="sm" disabled={generando === "contrato" || faltantesContrato.length > 0}>
              {generando === "contrato" ? "Generando…" : "Generar"}
            </Button>
          </form>
          <ChecklistNotice faltantes={faltantesContrato} />
        </div>

        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">Factura</p>
          <form onSubmit={generarFactura} className="space-y-2">
            <div className="flex items-end gap-2">
              <Field label="Cuantía (€)">
                <Input type="number" min="0" step="0.01" value={cuantia} onChange={(event) => setCuantia(event.target.value)} />
              </Field>
              <Field label="Concepto">
                <Input value={concepto} onChange={(event) => setConcepto(event.target.value)} />
              </Field>
              <Button type="submit" size="sm" disabled={generando === "factura" || faltantesFactura.length > 0}>
                {generando === "factura" ? "Generando…" : "Generar"}
              </Button>
            </div>
          </form>
          <ChecklistNotice faltantes={faltantesFactura} />
        </div>
      </div>

      <div className="mt-6">
        <Field label="Email de destino para envíos">
          <Input value={emailDestino} onChange={(event) => setEmailDestino(event.target.value)} placeholder="cliente@ejemplo.com" />
        </Field>
      </div>

      {notice && (
        <Notice tone="info" className="mt-3">
          {notice}
        </Notice>
      )}

      <div className="mt-6">
        {loading && <Spinner />}
        {!loading && documentos.length === 0 && <EmptyState title="Sin documentos generados todavía." />}
        {!loading && documentos.length > 0 && (
          <div className="space-y-2">
            {documentos.map((doc) => (
              <div key={doc.id} className="flex items-center justify-between gap-3 rounded-lg bg-surface-container-low p-3 text-sm">
                <div>
                  <p className="font-medium capitalize text-on-surface">
                    {doc.tipo} {doc.numero || ""}
                  </p>
                  <p className="text-xs text-on-surface-variant">
                    {formatDateTime(doc.created_at)}
                    {doc.enviado_at && ` · enviado ${formatDateTime(doc.enviado_at)} a ${doc.email_destino}`}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <EstadoChip dominio="documento_estado" valor={doc.estado} />
                  <a href={api.documentosComerciales.pdfUrl(doc.id)} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                    Descargar PDF
                  </a>
                  <Button size="sm" variant="secondary" onClick={() => enviar(doc)} disabled={enviando === doc.id}>
                    {enviando === doc.id ? "Enviando…" : "Enviar por email"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
