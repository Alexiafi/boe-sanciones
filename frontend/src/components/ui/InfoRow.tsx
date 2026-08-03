/** Shared by the sanción and cliente detail pages — previously duplicated
 * verbatim in both files. */
export function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-4 py-2.5">
      <span className="text-sm text-on-surface-variant">{label}</span>
      <span className="max-w-[60%] text-right text-sm font-medium text-on-surface">{value}</span>
    </div>
  );
}
