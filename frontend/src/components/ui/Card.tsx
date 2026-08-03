import { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Tonal-layering card: surface-container-lowest floating over the app's
 * surface background. No border — elevation reads from the tone jump plus a
 * faint ambient shadow, per DESIGN.md §4. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg bg-surface-container-lowest p-6 shadow-ambient",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 flex items-center justify-between gap-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 className={cn("text-lg font-semibold tracking-[-0.02em] text-on-surface", className)} {...props} />
  );
}
