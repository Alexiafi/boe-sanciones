/** Shared by the sanción and cliente detail pages — previously duplicated
 * verbatim in both files. */
export function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-4 py-3">
      <span className="text-[11px] font-semibold uppercase tracking-[0.055em] text-on-surface-variant">{label}</span>
      <span className="max-w-[62%] text-right text-sm font-semibold text-primary">{value}</span>
    </div>
  );
}
