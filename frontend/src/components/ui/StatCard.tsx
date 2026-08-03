import { Card } from "./Card";

export function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <Card>
      <p className="text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">{label}</p>
      <p className="mt-2 text-3xl font-bold tracking-[-0.02em] text-on-surface">{value}</p>
      {sub && <p className="mt-1 text-xs text-on-surface-variant">{sub}</p>}
    </Card>
  );
}
