import { cn } from "@/lib/utils";

/** role="status" + aria-live so a screen reader announces "loading" once
 * instead of the spinner being silently invisible to assistive tech. */
export function Spinner({ className, label = "Cargando…" }: { className?: string; label?: string }) {
  return (
    <div role="status" aria-live="polite" className={cn("flex items-center justify-center py-12", className)}>
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-outline-variant border-b-primary" />
      <span className="sr-only">{label}</span>
    </div>
  );
}
