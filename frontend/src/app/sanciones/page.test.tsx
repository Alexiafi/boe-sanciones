import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SancionesPage from "./page";

const replace = vi.fn();
// Stable references, like Next's own hooks: a new router per render would
// re-create the page's fetch callback and loop forever.
const router = { replace };
const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => params,
}));

vi.mock("@/lib/api", () => ({
  api: {
    sanciones: { list: vi.fn() },
    documentos: { archivoUrl: (id: number) => `http://api/doc/${id}` },
  },
}));

import { api } from "@/lib/api";

const listMock = api.sanciones.list as unknown as ReturnType<typeof vi.fn>;

function aviso(overrides: Record<string, unknown> = {}) {
  return {
    id: 1, boe_document_id: 1, codigo: "OP-2026-000001", estado_oportunidad: "nueva", nombre: null,
    identificador: "B12345678", importe_multa_eur: 200, importe_deuda_eur: null, dominio_material: null,
    contacto_estado: "pendiente", telefono: null, email: null, fecha_publicacion: "2026-10-01",
    url_documento: null, tiene_copia_local: false, cliente_id: null, cliente_nombre: null, cliente_estado: null,
    nombre_mostrado: "B12345678", otras_notificaciones: 0, ya_contactado: false, ultima_gestion: null,
    notas_del_titular: 0, ...overrides,
  };
}

const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 20, pages: 1 });

describe("SancionesPage", () => {
  beforeEach(() => {
    listMock.mockReset();
    replace.mockReset();
  });

  it("shows who the party is when the notice carries only a CIF: client name and badge", async () => {
    listMock.mockResolvedValue(page([
      aviso({ cliente_id: 7, cliente_nombre: "Acme Logística SL", cliente_estado: "activo", nombre_mostrado: "Acme Logística SL" }),
    ]));
    render(<SancionesPage />);
    expect(await screen.findByText("Acme Logística SL")).toBeInTheDocument();
    const badge = screen.getByText("Ya es cliente");
    expect(badge.closest("a")).toHaveAttribute("href", "/clientes/7");
  });

  it("flags an information-only client differently from a contracted one", async () => {
    listMock.mockResolvedValue(page([aviso({ cliente_id: 8, cliente_nombre: "Solo Info SL", cliente_estado: "informado", nombre_mostrado: "Solo Info SL" })]));
    render(<SancionesPage />);
    expect(await screen.findByText("Cliente · solo info")).toBeInTheDocument();
  });

  it("warns when another notice of the same DNI/CIF was already contacted", async () => {
    listMock.mockResolvedValue(page([
      aviso({ id: 2, ya_contactado: true, ultima_gestion: "2026-09-30T10:00:00Z", otras_notificaciones: 2 }),
    ]));
    render(<SancionesPage />);
    expect(await screen.findByText(/Contactado antes · 30\/09\/2026/)).toBeInTheDocument();
    expect(screen.getByText("+2 avisos")).toBeInTheDocument();
  });

  it("sends the default 30-day window, but searches ALL dates when the user types a DNI/CIF", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue(page([]));
    render(<SancionesPage />);
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(listMock.mock.calls[0][0]).toHaveProperty("fecha_desde");
    expect(listMock.mock.calls[0][0]).toHaveProperty("fecha_hasta");

    await user.type(screen.getByPlaceholderText(/Código, nombre, identificador/), "12345678Z");
    await waitFor(() => {
      const ultima = listMock.mock.calls[listMock.mock.calls.length - 1][0];
      expect(ultima).toMatchObject({ search: "12345678Z" });
      expect(ultima).not.toHaveProperty("fecha_desde");
      expect(ultima).not.toHaveProperty("fecha_hasta");
    });
  });

  it("filters by already-client, previous contact and phone", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue(page([]));
    render(<SancionesPage />);
    await waitFor(() => expect(listMock).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText(/^Cliente/), "false");
    await user.selectOptions(screen.getByLabelText(/Gestión previa/), "false");
    await user.selectOptions(screen.getByLabelText(/^Teléfono/), "true");

    await waitFor(() => {
      const ultima = listMock.mock.calls[listMock.mock.calls.length - 1][0];
      expect(ultima).toMatchObject({ es_cliente: "false", gestion_previa: "false", solo_con_telefono: "true" });
    });
  });
});
