"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ConfiguracionRuntime, EstadoEntorno, ModoExtraccion } from "@/lib/types";
import { Button, Card, CardTitle, Chip, ErrorState, Field, Input, Notice, PageHeader, Select, Spinner } from "@/components/ui";

const MODO_LABEL: Record<ModoExtraccion, string> = {
  tiempo_real: "Tiempo real (resultados en minutos, precio completo)",
  batch: "Batch (≈50 % más barato, resultados en horas — hasta 24 h)",
};

function EstadoLinea({ label, ok, motivo }: { label: string; ok: boolean; motivo: string | null }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <div>
        <p className="text-sm font-medium text-on-surface">{label}</p>
        {!ok && motivo && <p className="mt-0.5 text-xs text-on-surface-variant">{motivo}</p>}
      </div>
      <Chip label={ok ? "Activo" : "Inactivo"} tone={ok ? "success" : "neutral"} />
    </div>
  );
}

export default function ConfiguracionPage() {
  const [config, setConfig] = useState<ConfiguracionRuntime | null>(null);
  const [entorno, setEntorno] = useState<EstadoEntorno | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await api.configuracion.get();
      setConfig(res.configuracion);
      setEntorno(res.entorno);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const guardar = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!config) return;
    setSaving(true);
    setNotice(null);
    try {
      const res = await api.configuracion.update(config);
      setConfig(res.configuracion);
      setEntorno(res.entorno);
      setNotice({ tone: "success", text: "Configuración guardada. Se aplica a la siguiente ejecución, sin reiniciar nada." });
    } catch (err) {
      setNotice({ tone: "danger", text: `No se pudo guardar: ${err instanceof Error ? err.message : String(err)}` });
    } finally {
      setSaving(false);
    }
  };

  const set = <K extends keyof ConfiguracionRuntime>(key: K, value: ConfiguracionRuntime[K]) =>
    setConfig((prev) => (prev ? { ...prev, [key]: value } : prev));

  return (
    <div>
      <PageHeader
        title="Configuración"
        description="Cómo se usa OpenAI en la captación diaria y en el histórico. Se guarda en la base de datos y se aplica de inmediato."
      />

      {loading && <Spinner />}
      {!loading && error && <ErrorState onRetry={load} />}

      {!loading && !error && config && entorno && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
          <form onSubmit={guardar}>
            <Card>
              <CardTitle>Extracción diaria (OpenAI)</CardTitle>
              <p className="mt-1 text-sm text-on-surface-variant">
                La captación del BOE/TEU se ejecuta sola cada 30 minutos entre las 07:00 y las 11:30 (para que tengas las
                multas del día a primera hora) y cada hora hasta las 21:30; cada pasada solo descarga lo que sea nuevo.
                Aquí decides si además extrae los datos de cada sanción con OpenAI y de qué manera.
              </p>

              {!entorno.openai_extraccion_disponible && (
                <Notice tone="warning" className="mt-4">
                  La extracción OpenAI no está disponible en el servidor: {entorno.openai_extraccion_motivo} Mientras tanto la
                  captación diaria solo indexa los documentos (gratis) y estas opciones no tienen efecto.
                </Notice>
              )}

              <div className="mt-5 space-y-4">
                <label className="flex items-start gap-3 rounded-xl bg-surface-container-low p-4 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={config.extraccion_automatica}
                    onChange={(event) => set("extraccion_automatica", event.target.checked)}
                  />
                  <span>
                    <span className="block font-medium text-on-surface">Extraer automáticamente cada día</span>
                    <span className="block text-on-surface-variant">
                      Con esto activo, las sanciones del día aparecen en el Panel de Multas sin pulsar nada. Si lo
                      desactivas, solo se indexan los documentos y tendrás que lanzar la extracción a mano desde Operación.
                    </span>
                  </span>
                </label>

                <Field
                  label="Modo de extracción diaria"
                  hint="Batch usa la Batch API de OpenAI: mismo modelo y mismos resultados, a mitad de precio, pero los datos llegan cuando OpenAI termina (normalmente en menos de una hora; máximo 24 h). Tiempo real los tiene en pocos minutos."
                >
                  <Select value={config.extraccion_modo} onChange={(event) => set("extraccion_modo", event.target.value as ModoExtraccion)}>
                    {(Object.keys(MODO_LABEL) as ModoExtraccion[]).map((modo) => (
                      <option key={modo} value={modo}>
                        {MODO_LABEL[modo]}
                      </option>
                    ))}
                  </Select>
                </Field>

                <Field
                  label="Modo de extracción del histórico de clientes"
                  hint="Extracción bajo demanda de documentos antiguos desde la ficha del cliente. Nadie la espera al momento, así que batch es lo razonable."
                >
                  <Select
                    value={config.historico_extraccion_modo}
                    onChange={(event) => set("historico_extraccion_modo", event.target.value as ModoExtraccion)}
                  >
                    {(Object.keys(MODO_LABEL) as ModoExtraccion[]).map((modo) => (
                      <option key={modo} value={modo}>
                        {MODO_LABEL[modo]}
                      </option>
                    ))}
                  </Select>
                </Field>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="Máx. documentos a OpenAI por ejecución" hint="Tope de gasto por día. Un día normal tiene entre 600 y 900 documentos candidatos (BOE + TEU).">
                    <Input
                      type="number"
                      min={0}
                      max={5000}
                      value={config.extraccion_max_docs_por_ejecucion}
                      onChange={(event) => set("extraccion_max_docs_por_ejecucion", Number(event.target.value))}
                    />
                  </Field>
                  <Field label="Máx. notificaciones del TEU por ejecución" hint="El TEU publica entre 600 y 1.200 avisos sancionadores al día. Bajar esto reduce tiempo y coste, pero deja avisos sin captar.">
                    <Input
                      type="number"
                      min={0}
                      max={5000}
                      value={config.teu_max_por_ejecucion}
                      onChange={(event) => set("teu_max_por_ejecucion", Number(event.target.value))}
                    />
                  </Field>
                </div>
              </div>

              {notice && (
                <Notice tone={notice.tone} className="mt-4">
                  {notice.text}
                </Notice>
              )}

              <div className="mt-5">
                <Button type="submit" disabled={saving}>
                  {saving ? "Guardando…" : "Guardar configuración"}
                </Button>
              </div>
            </Card>
          </form>

          <Card>
            <CardTitle>Estado del servidor (.env)</CardTitle>
            <p className="mt-1 text-sm text-on-surface-variant">
              Puertas permanentes que se configuran en el archivo <code>.env</code> del servidor. Solo lectura.
            </p>
            <div className="mt-3 divide-y divide-outline-variant/15">
              <EstadoLinea label={`Extracción OpenAI · ${entorno.openai_modelo}`} ok={entorno.openai_extraccion_disponible} motivo={entorno.openai_extraccion_motivo} />
              <EstadoLinea label="Enriquecimiento de contacto" ok={entorno.enriquecimiento_disponible} motivo={entorno.enriquecimiento_motivo} />
              <EstadoLinea label="Envío de email (contrato / factura / resumen diario)" ok={entorno.email_disponible} motivo={entorno.email_motivo} />
              <EstadoLinea
                label="Backfill histórico (4 años)"
                ok={entorno.backfill_historico_habilitado}
                motivo="Desactivado a propósito hasta la instalación definitiva: se activa con HISTORICO_BACKFILL_ENABLED=true y se lanza a mano desde Operación."
              />
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
