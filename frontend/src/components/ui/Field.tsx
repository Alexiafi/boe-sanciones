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
  "w-full rounded-lg bg-surface-container-high px-3 py-2.5 text-sm text-on-surface placeholder:text-on-surface-variant " +
  "outline-none transition-colors focus:bg-surface-container-lowest focus:ghost-border focus:ring-2 focus:ring-primary/40";

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
      <span className="mb-1.5 block text-xs font-medium uppercase tracking-[0.05em] text-on-surface-variant">
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
