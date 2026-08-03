import { ButtonHTMLAttributes, forwardRef } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm";

const base =
  "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-all " +
  "disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface";

const sizes: Record<Size, string> = {
  md: "min-h-11 px-5 py-3 text-sm",
  sm: "min-h-9 px-4 py-2 text-xs",
};

const variants: Record<Variant, string> = {
  primary: "gradient-primary text-on-primary shadow-[0_10px_24px_rgba(6,31,71,0.18)] hover:-translate-y-0.5 hover:shadow-[0_14px_30px_rgba(6,31,71,0.24)]",
  secondary: "border border-outline-variant bg-white text-primary shadow-sm hover:border-secondary hover:bg-surface-bright",
  ghost: "bg-transparent text-primary hover:bg-secondary-container/55",
  danger: "bg-error text-on-error hover:opacity-90",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => (
    <button ref={ref} className={cn(base, sizes[size], variants[variant], className)} {...props} />
  )
);
Button.displayName = "Button";

interface LinkButtonProps {
  href: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: React.ReactNode;
}

export function LinkButton({ href, variant = "secondary", size = "md", className, children }: LinkButtonProps) {
  return (
    <Link href={href} className={cn(base, sizes[size], variants[variant], className)}>
      {children}
    </Link>
  );
}
