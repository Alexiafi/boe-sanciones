import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NotificacionesPage from "./page";

vi.mock("@/lib/api", () => ({
  api: {
    notificaciones: {
      list: vi.fn(),
      markRead: vi.fn(),
      markAllRead: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const listMock = api.notificaciones.list as unknown as ReturnType<typeof vi.fn>;

const emptyPage = { items: [], total: 0, page: 1, page_size: 20, pages: 0 };

describe("NotificacionesPage", () => {
  beforeEach(() => {
    listMock.mockReset();
    listMock.mockResolvedValue(emptyPage);
  });

  it("requests solo_clientes=true when the filter is checked", async () => {
    const user = userEvent.setup();
    render(<NotificacionesPage />);
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));
    expect(listMock.mock.calls[0][0]).not.toHaveProperty("solo_clientes");

    await user.click(screen.getByRole("checkbox", { name: "Solo mis clientes" }));

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
    expect(listMock.mock.calls[1][0]).toMatchObject({ solo_clientes: "true" });
  });

  it("renders a 'Ver cliente' link for client-linked notifications", async () => {
    listMock.mockResolvedValue({
      items: [
        {
          id: 1, tipo: "nueva_sancion_cliente", titulo: "Nueva sanción de cliente: Acme",
          mensaje: null, leida: false, sancionado_id: 5, cliente_id: 7, created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1, page: 1, page_size: 20, pages: 1,
    });
    render(<NotificacionesPage />);
    await waitFor(() => expect(screen.getByText("Ver cliente")).toBeInTheDocument());
    expect(screen.getByText("Ver cliente").closest("a")).toHaveAttribute("href", "/clientes/7");
  });
});
