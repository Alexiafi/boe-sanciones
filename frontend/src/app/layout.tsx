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
    <html lang="es" className={inter.variable}>
      <body className="antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-on-primary"
        >
          Saltar al contenido
        </a>
        <Sidebar />
        <main id="main-content" className="ml-64 min-h-screen p-8">
          {children}
        </main>
      </body>
    </html>
  );
}
