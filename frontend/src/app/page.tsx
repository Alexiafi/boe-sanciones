"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CalendarCheck, Clock3, Gauge, Landmark, Search, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { DashboardStats } from "@/lib/types";
import { Card, CardTitle, Chip, EmptyState, ErrorState, LinkButton, PageHeader, Spinner, StatCard } from "@/components/ui";
import { formatDateTime } from "@/lib/formatters";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    api.dashboard
      .stats()
      .then((data) => setStats(data as unknown as DashboardStats))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="Resumen de oportunidades"
        description="Toda la actividad comercial nacida del BOE, priorizada y lista para actuar."
        actions={
          <>
            <LinkButton href="/consulta" variant="secondary"><Search className="h-4 w-4" /> Consulta rápida</LinkButton>
            <LinkButton href="/sanciones" variant="primary">Ver panel <ArrowRight className="h-4 w-4" /></LinkButton>
          </>
        }
      />

      <section className="relative mb-8 overflow-hidden rounded-2xl bg-primary px-6 py-7 text-white shadow-[0_22px_60px_rgba(6,31,71,0.2)] sm:px-8 lg:mb-10 lg:px-10 lg:py-9">
        <div className="absolute inset-0 opacity-35 [background-image:radial-gradient(circle_at_1px_1px,rgba(255,255,255,.18)_1px,transparent_0)] [background-size:22px_22px]" />
        <div className="absolute -right-20 -top-32 h-80 w-80 rounded-full bg-[#315b91]/55 blur-2xl" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-2xl">
            <div className="mb-3 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.17em] text-[#b9cae2]">
              <Sparkles className="h-3.5 w-3.5" /> Inteligencia comercial diaria
            </div>
            <h2 className="text-2xl font-extrabold leading-tight tracking-[-0.035em] sm:text-3xl">Convierte publicaciones oficiales en oportunidades reales.</h2>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-white/66">Consulta nuevas sanciones, completa los datos de contacto y gestiona cada expediente hasta convertirlo en cliente.</p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-3 text-xs">
            <Link href="/sanciones" className="flex min-w-40 items-center gap-3 rounded-xl border border-white/10 bg-white/10 px-4 py-3.5 font-semibold text-white backdrop-blur hover:bg-white/16">
              <ShieldCheck className="h-5 w-5 text-[#ffd398]" /> Multas del día
            </Link>
            <Link href="/scraping" className="flex min-w-40 items-center gap-3 rounded-xl border border-white/10 bg-white/10 px-4 py-3.5 font-semibold text-white backdrop-blur hover:bg-white/16">
              <Gauge className="h-5 w-5 text-[#bcd3f1]" /> Operación
            </Link>
          </div>
        </div>
      </section>

      {loading && <Spinner />}
      {!loading && error && <ErrorState onRetry={load} />}
      {!loading && !error && stats && (
        <>
          <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Total documentos" value={stats.total_documentos} sub="publicaciones incorporadas" />
            <StatCard label="Total sancionados" value={stats.total_sancionados} sub="oportunidades identificadas" />
            <StatCard label="Sancionados hoy" value={stats.sancionados_hoy} sub={`${stats.sancionados_semana.toLocaleString("es-ES")} esta semana`} />
            <StatCard label="Notificaciones" value={stats.notificaciones_sin_leer} sub="alertas pendientes de revisar" />
            <StatCard label="Alertas de clientes" value={stats.alertas_clientes_sin_leer} sub="nuevas sanciones de tus clientes" />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.05fr_.95fr]">
            <div className="space-y-6">
              <Card className="overflow-hidden p-0">
                <div className="flex items-center justify-between border-b border-outline-variant/55 px-6 py-5">
                  <div className="flex items-center gap-3">
                    <span className="grid h-10 w-10 place-items-center rounded-xl bg-secondary-container text-primary"><CalendarCheck className="h-5 w-5" /></span>
                    <div><CardTitle>Última captura BOE</CardTitle><p className="mt-0.5 text-xs text-on-surface-variant">Estado del proceso de incorporación más reciente</p></div>
                  </div>
                  <Link href="/scraping" className="text-xs font-bold text-primary hover:underline">Ver operación</Link>
                </div>
                {stats.ultimo_scraping.fecha ? (
                  <div className="grid grid-cols-2 gap-px bg-outline-variant/50 sm:grid-cols-4">
                    <Metric label="Fecha BOE" value={stats.ultimo_scraping.fecha} />
                    <div className="bg-white px-5 py-5"><p className="text-[10px] font-bold uppercase tracking-[0.1em] text-on-surface-variant">Estado</p><div className="mt-2"><Chip label={stats.ultimo_scraping.status ?? "—"} tone={stats.ultimo_scraping.status === "completed" ? "success" : stats.ultimo_scraping.status === "failed" ? "danger" : "warning"} /></div></div>
                    <Metric label="Extraídos" value={(stats.ultimo_scraping.extracted ?? 0).toLocaleString("es-ES")} />
                    <Metric label="Finalizado" value={stats.ultimo_scraping.finished_at ? formatDateTime(stats.ultimo_scraping.finished_at) : "En curso"} />
                  </div>
                ) : <div className="p-6"><EmptyState title="Aún no se ha ejecutado ningún scraping." /></div>}
              </Card>

              <Card>
                <div className="mb-5 flex items-center justify-between"><div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-tertiary-fixed text-tertiary-container"><Landmark className="h-5 w-5" /></span><CardTitle>Organismos con más actividad</CardTitle></div><span className="text-[9px] font-bold uppercase tracking-[0.13em] text-outline">Últimos 30 días</span></div>
                {stats.top_organismos.length > 0 ? (
                  <div className="space-y-4">
                    {stats.top_organismos.map((org, index) => {
                      const maximum = Math.max(...stats.top_organismos.map((item) => item.total), 1);
                      return <div key={org.nombre}><div className="mb-1.5 flex items-center justify-between gap-3"><span className="truncate text-sm font-medium text-primary" title={org.nombre}>{index + 1}. {org.nombre}</span><span className="text-xs font-bold text-primary">{org.total}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-surface-container-low"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(8, (org.total / maximum) * 100)}%` }} /></div></div>;
                    })}
                  </div>
                ) : <EmptyState title="Sin datos aún." />}
              </Card>
            </div>

            <div className="space-y-6">
              <Card>
                <div className="mb-5 flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-error-container text-error"><ShieldCheck className="h-5 w-5" /></span><CardTitle>Infracciones por gravedad</CardTitle></div>
                {stats.infracciones_por_tipo.length > 0 ? <div className="space-y-3">{stats.infracciones_por_tipo.map((inf) => <div key={inf.tipo} className="flex items-center justify-between rounded-xl bg-surface-container-low/75 px-4 py-3"><span className="text-sm font-semibold capitalize text-primary">{inf.tipo?.replace("_", " ") || "Sin tipo"}</span><Chip label={String(inf.total)} tone={inf.tipo === "muy_grave" ? "danger" : inf.tipo === "grave" ? "warning" : "neutral"} /></div>)}</div> : <EmptyState title="Sin datos aún." />}
              </Card>

              <Card>
                <div className="mb-5 flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-secondary-container text-primary"><Clock3 className="h-5 w-5" /></span><CardTitle>Acciones recomendadas</CardTitle></div>
                <div className="space-y-2">
                  <QuickLink href="/sanciones" title="Revisar nuevas oportunidades" description="Prioriza las publicaciones de hoy" />
                  <QuickLink href="/consulta" title="Consultar un DNI o CIF" description="Busca en todo el índice histórico" />
                  <QuickLink href="/clientes" title="Abrir la cartera de clientes" description="Continúa el seguimiento comercial" />
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="bg-white px-5 py-5"><p className="text-[10px] font-bold uppercase tracking-[0.1em] text-on-surface-variant">{label}</p><p className="mt-2 text-sm font-bold text-primary">{value}</p></div>;
}

function QuickLink({ href, title, description }: { href: string; title: string; description: string }) {
  return <Link href={href} className="group flex items-center gap-4 rounded-xl border border-transparent px-3 py-3 hover:border-outline-variant hover:bg-surface-bright"><span className="grid h-8 w-8 place-items-center rounded-lg bg-surface-container-low text-primary"><ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" /></span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-primary">{title}</span><span className="mt-0.5 block text-xs text-on-surface-variant">{description}</span></span></Link>;
}
