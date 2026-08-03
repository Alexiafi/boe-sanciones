import { ButtonHTMLAttributes, forwardRef } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "md" | "sm";

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-shadow " +
  "disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface";

const sizes: Record<Size, string> = {
  md: "px-6 py-3.5 text-sm",
  sm: "px-4 py-2 text-sm",
};

const variants: Record<Variant, string> = {
  primary: "gradient-primary text-on-primary shadow-ambient hover:shadow-lg",
  secondary: "bg-surface-container-high text-on-surface hover:bg-surface-container-highest",
  ghost: "bg-transparent text-on-surface hover:bg-surface-container-low",
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
