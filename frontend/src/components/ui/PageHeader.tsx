import { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-5 lg:mb-10">
      <div>
        <div className="mb-2 flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.19em] text-outline">
          <span className="h-px w-5 bg-outline-variant" /> BOE Oportunidades
        </div>
        <h1 className="text-[2rem] font-extrabold leading-[1.08] tracking-[-0.045em] text-primary sm:text-[2.45rem]">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-on-surface-variant sm:text-base">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
