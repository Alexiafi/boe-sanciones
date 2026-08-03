import { cn } from "@/lib/utils";

type Tone = "info" | "warning" | "danger" | "success";

const toneClasses: Record<Tone, string> = {
  info: "bg-secondary-container text-on-secondary-container",
  warning: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
  danger: "bg-error-container text-on-error-container",
  success: "bg-success-container text-on-success-container",
};

/** role="alert" (or "status" for info/success) so a save confirmation or a
 * validation error is actually announced, not just visually present. Used
 * for the R-1 TEU-limitation callout, save confirmations, and inline
 * validation summaries. */
export function Notice({
  children,
  tone = "info",
  className,
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={cn("rounded-xl border border-current/10 px-4 py-3.5 text-sm leading-relaxed", toneClasses[tone], className)}
    >
      {children}
    </div>
  );
}
