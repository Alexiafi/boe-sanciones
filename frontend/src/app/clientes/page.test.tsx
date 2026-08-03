import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ClientesPage from "./page";

vi.mock("@/lib/api", () => ({
  api: {
    clientes: {
      list: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const listMock = api.clientes.list as unknown as ReturnType<typeof vi.fn>;

describe("ClientesPage", () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it("shows a spinner while loading", async () => {
    listMock.mockReturnValue(new Promise(() => {})); // never resolves
    render(<ClientesPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows an empty state when there are no clients", async () => {
    listMock.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20, pages: 0 });
    render(<ClientesPage />);
    await waitFor(() => expect(screen.getByText("No se encontraron clientes.")).toBeInTheDocument());
  });

  it("shows an error state with retry when the request fails", async () => {
    listMock.mockRejectedValue(new Error("network down"));
    render(<ClientesPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("renders client rows when data is returned", async () => {
    listMock.mockResolvedValue({
      items: [
        {
          id: 1, codigo: "CLI-2026-0001", nombre_razon_social: "Acme Logística SL", cif_nif: "B12345674",
          matriculas: [], estado_cliente: "activo", deuda_pendiente_eur: 0, sancion_origen_id: 1, created_at: "2026-01-01",
        },
      ],
      total: 1, page: 1, page_size: 20, pages: 1,
    });
    render(<ClientesPage />);
    await waitFor(() => expect(screen.getByText("Acme Logística SL")).toBeInTheDocument());
    expect(screen.getByText("CLI-2026-0001")).toBeInTheDocument();
  });
});
