import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Sidebar } from "@/components/ui";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "BOE Oportunidades",
  description: "Captación y gestión de sanciones publicadas en el Boletín Oficial del Estado",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={inter.variable} data-theme="light">
      <body>
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[80] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-on-primary"
        >
          Saltar al contenido
        </a>
        <Sidebar />
        <main id="main-content" className="min-h-screen px-5 pb-12 pt-24 lg:ml-[17rem] lg:px-10 lg:pb-16 lg:pt-28 xl:px-14">
          <div className="mx-auto w-full max-w-[1480px]">{children}</div>
        </main>
        <footer className="hidden border-t border-outline-variant/60 bg-white/60 px-10 py-5 text-[10px] font-medium uppercase tracking-[0.14em] text-on-surface-variant lg:ml-[17rem] lg:flex lg:items-center lg:justify-between">
          <span>© 2026 BOE Oportunidades · Gestión de sanciones</span>
          <span>Entorno privado · Datos protegidos</span>
        </footer>
      </body>
    </html>
  );
}
