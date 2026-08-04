"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bell,
  Building2,
  ChevronRight,
  CircleUserRound,
  FileClock,
  Gauge,
  History,
  LayoutDashboard,
  Search,
  Settings2,
  ShieldCheck,
  UsersRound,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Inicio", icon: LayoutDashboard },
  { href: "/sanciones", label: "Panel de Multas", icon: ShieldCheck },
  { href: "/historial", label: "Historial", icon: History },
  { href: "/clientes", label: "Clientes", icon: UsersRound },
  { href: "/consulta", label: "Consulta DNI/CIF", icon: Search },
  { href: "/notificaciones", label: "Notificaciones", icon: Bell },
  { href: "/scraping", label: "Operación", icon: Gauge },
];

const MOBILE_LINKS = LINKS.slice(0, 5);

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  const [unread, setUnread] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.notificaciones
      .unreadCount()
      .then((res) => {
        if (!cancelled) setUnread((res as { count: number }).count);
      })
      .catch(() => {
        if (!cancelled) setUnread(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  return (
    <>
      <header className="fixed inset-x-0 top-0 z-50 flex h-[4.75rem] items-center border-b border-outline-variant/70 bg-white/95 px-5 backdrop-blur-xl lg:left-[17rem] lg:px-10 xl:px-14">
        <Link href="/" className="mr-auto flex items-center gap-3 lg:hidden" aria-label="BOE Oportunidades, inicio">
          <BrandMark />
          <div>
            <p className="text-sm font-extrabold tracking-[-0.035em] text-primary">BOE Oportunidades</p>
            <p className="text-[9px] font-semibold uppercase tracking-[0.18em] text-on-surface-variant">Gestión editorial</p>
          </div>
        </Link>
        <div className="hidden lg:block">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Área de trabajo</p>
          <p className="mt-0.5 text-sm font-semibold text-primary">Inteligencia comercial BOE</p>
        </div>
        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          <Link
            href="/consulta"
            className="hidden h-10 w-60 items-center gap-2.5 rounded-full bg-surface-container-low px-4 text-sm text-on-surface-variant hover:bg-surface-container-high sm:flex"
          >
            <Search className="h-4 w-4" strokeWidth={1.8} />
            <span>Buscar DNI, CIF o nombre…</span>
          </Link>
          <Link href="/notificaciones" aria-label="Notificaciones" className="relative grid h-10 w-10 place-items-center rounded-full text-primary hover:bg-surface-container-low">
            <Bell className="h-[19px] w-[19px]" strokeWidth={1.8} />
            {!!unread && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-error ring-2 ring-white" />}
          </Link>
          <div className="grid h-9 w-9 place-items-center rounded-full bg-primary text-white shadow-sm" aria-label="Perfil de usuario">
            <CircleUserRound className="h-5 w-5" strokeWidth={1.8} />
          </div>
        </div>
      </header>

      <aside className="fixed inset-y-0 left-0 z-[60] hidden w-[17rem] flex-col border-r border-outline-variant/70 bg-sidebar-bg lg:flex">
        <Link href="/" className="flex h-[7.25rem] items-center gap-3 px-7" aria-label="BOE Oportunidades, inicio">
          <BrandMark />
          <div>
            <h1 className="text-[15px] font-extrabold tracking-[-0.035em] text-primary">BOE Oportunidades</h1>
            <p className="mt-0.5 text-[9px] font-semibold uppercase tracking-[0.2em] text-on-surface-variant">Gestión editorial</p>
          </div>
        </Link>

        <div className="px-4">
          <p className="px-3 pb-2 text-[9px] font-bold uppercase tracking-[0.18em] text-outline">Navegación</p>
          <nav aria-label="Navegación principal" className="space-y-1">
            {LINKS.map((link) => {
              const active = isActive(pathname, link.href);
              const Icon = link.icon;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group flex min-h-11 items-center gap-3 rounded-xl px-3 text-[13px] font-medium transition-all",
                    active
                      ? "bg-white font-semibold text-primary shadow-[0_8px_24px_rgba(17,39,68,0.08)]"
                      : "text-sidebar-fg hover:bg-white/80 hover:text-primary"
                  )}
                >
                  <span className={cn("grid h-8 w-8 place-items-center rounded-lg", active ? "bg-secondary-container text-primary" : "text-sidebar-fg group-hover:text-primary")}>
                    <Icon className="h-[18px] w-[18px]" strokeWidth={active ? 2.2 : 1.8} />
                  </span>
                  <span className="flex-1">{link.label}</span>
                  {link.href === "/notificaciones" && !!unread ? (
                    <span className="rounded-full bg-error-container px-2 py-0.5 text-[9px] font-bold text-error">{unread > 99 ? "99+" : unread}</span>
                  ) : active ? (
                    <ChevronRight className="h-3.5 w-3.5 text-outline" />
                  ) : null}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="mt-auto px-4 pb-5">
          <div className="mb-3 rounded-2xl bg-primary p-4 text-white shadow-[0_14px_30px_rgba(6,31,71,0.2)]">
            <div className="mb-3 flex items-center gap-2 text-on-primary-container">
              <FileClock className="h-4 w-4" />
              <span className="text-[9px] font-bold uppercase tracking-[0.16em]">Cobertura activa</span>
            </div>
            <p className="text-sm font-semibold">Histórico BOE indexado</p>
            <p className="mt-1 text-[11px] leading-relaxed text-white/65">Consulta y seguimiento desde un único expediente.</p>
          </div>
          <Link href="/scraping" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-xs font-medium text-sidebar-fg hover:bg-white hover:text-primary">
            <Settings2 className="h-4 w-4" /> Configuración operativa
          </Link>
          <div className="mt-2 flex items-center gap-2 px-3 text-[9px] font-semibold uppercase tracking-[0.14em] text-outline">
            <Building2 className="h-3.5 w-3.5" /> Entorno privado · v1.0
          </div>
        </div>
      </aside>

      <nav className="fixed inset-x-3 bottom-3 z-[70] flex h-[4.15rem] items-center justify-around rounded-2xl border border-white/70 bg-primary px-1 text-white shadow-[0_18px_50px_rgba(6,31,71,0.35)] lg:hidden" aria-label="Navegación móvil">
        {MOBILE_LINKS.map((link) => {
          const active = isActive(pathname, link.href);
          const Icon = link.icon;
          return (
            <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} className={cn("flex min-w-14 flex-col items-center gap-1 rounded-xl px-2 py-2 text-[9px]", active ? "bg-white/14 text-white" : "text-white/62")}>
              <Icon className="h-[18px] w-[18px]" strokeWidth={active ? 2.3 : 1.8} />
              <span>{link.label === "Panel de Multas" ? "Multas" : link.label.replace(" DNI/CIF", "")}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}

function BrandMark() {
  return (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary text-[11px] font-black tracking-[-0.03em] text-white shadow-[0_10px_25px_rgba(6,31,71,0.22)]">
      BOE
    </span>
  );
}
