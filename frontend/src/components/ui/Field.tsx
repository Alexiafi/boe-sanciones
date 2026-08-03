import {
  InputHTMLAttributes,
  ReactElement,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  cloneElement,
  isValidElement,
  useId,
} from "react";
import { cn } from "@/lib/utils";

const controlClasses =
  "w-full min-h-11 rounded-xl border border-outline-variant/65 bg-surface-bright px-3.5 py-2.5 text-sm text-on-surface placeholder:text-on-surface-variant/70 " +
  "outline-none transition-all hover:border-outline focus:border-primary/40 focus:bg-white focus:ring-4 focus:ring-secondary-container/70";

/** Wraps a single Input/Select/Textarea with a proper <label htmlFor>,
 * auto-generating and wiring a matching id — fixes the pre-redesign pages'
 * placeholder-only filter inputs that had no accessible name. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactElement<{ id?: string }>;
}) {
  const id = useId();
  const control = isValidElement(children) ? cloneElement(children, { id }) : children;
  return (
    <label className="block text-sm" htmlFor={id}>
      <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.11em] text-on-surface-variant">
        {label}
      </span>
      {control}
      {hint && <span className="mt-1 block text-xs text-on-surface-variant">{hint}</span>}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(controlClasses, className)} {...props} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(controlClasses, className)} {...props}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(controlClasses, className)} {...props} />;
}
