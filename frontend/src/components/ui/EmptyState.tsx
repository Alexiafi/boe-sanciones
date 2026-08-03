import { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg bg-surface-container-low px-6 py-12 text-center">
      <p className="text-sm font-medium text-on-surface">{title}</p>
      {description && <p className="max-w-md text-sm text-on-surface-variant">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
