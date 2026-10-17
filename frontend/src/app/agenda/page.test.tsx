import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgendaPage from "./page";

vi.mock("@/lib/api", () => ({
  api: {
    agenda: { list: vi.fn(), resumen: vi.fn() },
    clientes: { updateAccion: vi.fn() },
  },
}));

import { api } from "@/lib/api";

const listMock = api.agenda.list as unknown as ReturnType<typeof vi.fn>;
const resumenMock = api.agenda.resumen as unknown as ReturnType<typeof vi.fn>;
const updateMock = api.clientes.updateAccion as unknown as ReturnType<typeof vi.fn>;

function item(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id, cliente_id: 10 + id, tipo: "llamada", titulo: `Acción ${id}`, fecha_programada: null, estado: "pendiente", notas: null,
    created_at: "2026-10-01T08:00:00Z", cliente_nombre: `Cliente ${id} SL`, cliente_codigo: `CLI-${id}`, vencida: false, ...overrides,
  };
}

describe("AgendaPage", () => {
  beforeEach(() => {
    listMock.mockReset();
    resumenMock.mockReset();
    updateMock.mockReset();
    resumenMock.mockResolvedValue({ vencidas: 1, hoy: 0, proximas: 1, sin_fecha: 1 });
  });

  it("groups pending actions as overdue / upcoming / undated and links to the client", async () => {
    const futura = new Date(Date.now() + 3 * 86_400_000).toISOString();
    listMock.mockResolvedValue([
      item(1, { fecha_programada: "2020-01-01T09:00:00Z", vencida: true }),
      item(2, { fecha_programada: futura }),
      item(3),
    ]);
    render(<AgendaPage />);
    expect(await screen.findByText(/Vencidas · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Próximas · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Sin fecha · 1/)).toBeInTheDocument();
    expect(screen.getByText("Cliente 2 SL").closest("a")).toHaveAttribute("href", "/clientes/12");
  });

  it("marks an action as done from the agenda", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([item(1)]);
    updateMock.mockResolvedValue({});
    render(<AgendaPage />);
    await user.click(await screen.findByRole("button", { name: "Hecha" }));
    await waitFor(() => expect(updateMock).toHaveBeenCalledWith(11, 1, { estado: "hecha" }));
  });

  it("explains where actions are created when there are none", async () => {
    listMock.mockResolvedValue([]);
    render(<AgendaPage />);
    expect(await screen.findByText("No hay acciones.")).toBeInTheDocument();
  });
});
