"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ConsultaItem, CoberturaTeu } from "@/lib/types";
import { Button, Card, CardTitle, Chip, EmptyState, Field, Input, Notice, PageHeader, Spinner } from "@/components/ui";
import { formatDate } from "@/lib/formatters";

const AVISO_TEU =
  "Uso interno. El índice propio combina lo acumulado del BOE y del TEU (dentro de su ventana pública de 90 días); " +
  "marca «incluir TEU público» solo si quieres además una consulta en vivo al buscador del TEU (requiere que el conector esté " +
  "activado en el servidor). Fuera de esa ventana, el TEU solo devuelve lo que este sistema haya acumulado por sí mismo.";

export default function ConsultaPage() {
  const [cif, setCif] = useState("");
  const [dni, setDni] = useState("");
  const [matricula, setMatricula] = useState("");
  const [nombre, setNombre] = useState("");
  const [incluirTeu, setIncluirTeu] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultados, setResultados] = useState<ConsultaItem[] | null>(null);
  const [avisos, setAvisos] = useState<string[]>([]);
  const [cobertura, setCobertura] = useState<CoberturaTeu | null>(null);

  const buscar = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!cif && !dni && !matricula && !nombre) {
      setError("Indica al menos un criterio: CIF, DNI, matrícula o nombre.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = (await api.historico.consulta({
        cif: cif || undefined, dni: dni || undefined, matricula: matricula || undefined,
        nombre: nombre || undefined, incluir_teu: incluirTeu,
      })) as unknown as { resultados: ConsultaItem[]; avisos: string[]; cobertura_teu: CoberturaTeu };
      setResultados(resp.resultados);
      setAvisos(resp.avisos);
      setCobertura(resp.cobertura_teu);
    } catch (err) {
      setError(`No se pudo completar la consulta: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader title="Consulta por DNI/CIF" description="Búsqueda interna en el índice histórico por identificador, matrícula o nombre." />

      <Notice tone="warning" className="mb-6">
        {AVISO_TEU}
      </Notice>

      <Card className="mb-6">
        <CardTitle>Identificación</CardTitle>
        <form onSubmit={buscar} className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="CIF">
            <Input value={cif} onChange={(event) => setCif(event.target.value)} placeholder="B12345674" />
          </Field>
          <Field label="DNI/NIE">
            <Input value={dni} onChange={(event) => setDni(event.target.value)} placeholder="12345678Z" />
          </Field>
          <Field label="Matrícula">
            <Input value={matricula} onChange={(event) => setMatricula(event.target.value)} placeholder="1234BCD" />
          </Field>
          <Field label="Nombre / razón social">
            <Input value={nombre} onChange={(event) => setNombre(event.target.value)} placeholder="José García / Acme Logística SL" />
          </Field>
          <div className="md:col-span-2">
            <label className="flex items-center gap-2 text-sm text-on-surface-variant">
              <input type="checkbox" checked={incluirTeu} onChange={(event) => setIncluirTeu(event.target.checked)} />
              Incluir búsqueda pública TEU en vivo
            </label>
          </div>
          <div className="md:col-span-2">
            <Button type="submit" disabled={loading}>
              {loading ? "Consultando…" : "Consultar histórico"}
            </Button>
          </div>
        </form>
        {error && (
          <Notice tone="danger" className="mt-4">
            {error}
          </Notice>
        )}
      </Card>

      {loading && <Spinner />}

      {!loading && resultados && (
        <Card>
          <CardTitle>Resultados</CardTitle>
          {avisos.map((aviso, index) => (
            <Notice key={index} tone="info" className="mt-3">
              {aviso}
            </Notice>
          ))}
          {cobertura && !cobertura.consulta_en_vivo && incluirTeu && (
            <Notice tone="warning" className="mt-3">
              La consulta en vivo al TEU no está activa: {cobertura.motivo_sin_consulta}
            </Notice>
          )}
          <div className="mt-4">
            {resultados.length === 0 ? (
              <EmptyState title="Sin coincidencias." description="Prueba con otro identificador o revisa la ortografía del nombre." />
            ) : (
              <div className="space-y-2">
                {resultados.map((item) => (
                  <div key={item.historico_doc_id} className="flex items-center justify-between gap-3 rounded-lg bg-surface-container-low p-3 text-sm">
                    <div>
                      <p className="font-medium text-on-surface">{item.titulo}</p>
                      <p className="text-xs text-on-surface-variant">
                        {formatDate(item.fecha_publicacion)} · vía {item.via_match} · score {item.score.toFixed(2)}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Chip label={item.fuente.toUpperCase()} tone={item.fuente === "teu" ? "primary" : "neutral"} />
                      {item.fuera_de_ventana_teu && <span className="text-[10px] uppercase text-on-surface-variant">Solo acumulado</span>}
                      {(item.url_pdf || item.url_html) && (
                        <a href={item.url_pdf || item.url_html || "#"} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">
                          Ver documento
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
