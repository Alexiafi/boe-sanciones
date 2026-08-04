import { BellRing, Database, FileStack, ShieldCheck, TrendingUp } from "lucide-react";
import { Card } from "./Card";

function visualFor(label: string) {
  const value = label.toLowerCase();
  if (value.includes("notific")) return { Icon: BellRing, tone: "bg-error-container text-error" };
  if (value.includes("hoy") || value.includes("cobertura teu")) return { Icon: TrendingUp, tone: "bg-tertiary-fixed text-tertiary-container" };
  if (value.includes("document")) return { Icon: FileStack, tone: "bg-secondary-container text-primary" };
  if (value.includes("sancion")) return { Icon: ShieldCheck, tone: "bg-secondary-container text-primary-container" };
  return { Icon: Database, tone: "bg-surface-container-high text-secondary" };
}

export function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  const { Icon, tone } = visualFor(label);
  return (
    <Card className="group relative min-h-[10.5rem] overflow-hidden transition-all hover:-translate-y-1 hover:shadow-[0_22px_55px_rgba(17,39,68,0.11)]">
      <div className="flex items-start justify-between gap-4">
        <span className={`grid h-11 w-11 place-items-center rounded-xl ${tone}`}>
          <Icon className="h-5 w-5" strokeWidth={1.8} />
        </span>
        <span className="text-[9px] font-bold uppercase tracking-[0.15em] text-outline">Resumen</span>
      </div>
      <p className="mt-5 text-[10px] font-bold uppercase tracking-[0.11em] text-on-surface-variant">{label}</p>
      <p className="mt-1 text-[2rem] font-extrabold leading-none tracking-[-0.045em] text-primary">{typeof value === "number" ? value.toLocaleString("es-ES") : value}</p>
      {sub && <p className="mt-2 text-xs text-on-surface-variant">{sub}</p>}
      <span className="absolute -bottom-10 -right-8 h-24 w-24 rounded-full bg-secondary-container/30 transition-transform group-hover:scale-125" />
    </Card>
  );
}
