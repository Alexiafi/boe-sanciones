import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VinculosBlock } from "./VinculosBlock";

vi.mock("@/lib/api", () => ({
  api: {
    clientes: {
      listVinculos: vi.fn(),
      addVinculo: vi.fn(),
      deleteVinculo: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const listMock = api.clientes.listVinculos as unknown as ReturnType<typeof vi.fn>;
const addMock = api.clientes.addVinculo as unknown as ReturnType<typeof vi.fn>;
const deleteMock = api.clientes.deleteVinculo as unknown as ReturnType<typeof vi.fn>;

const vinculoAlberto = {
  id: 1,
  cliente_id: 10,
  cliente_vinculado_id: null,
  rol: "administrador",
  nombre: "Alberto Garcia",
  tipo_persona: "fisica",
  identificador: "12345678Z",
  tipo_identificador: "DNI",
  telefono: null,
  email: null,
  notas: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("VinculosBlock", () => {
  beforeEach(() => {
    listMock.mockReset();
    addMock.mockReset();
    deleteMock.mockReset();
  });

  it("shows an empty state when there are no vínculos", async () => {
    listMock.mockResolvedValue([]);
    render(<VinculosBlock clienteId={10} />);
    await waitFor(() => expect(screen.getByText("Sin vínculos todavía.")).toBeInTheDocument());
  });

  it("renders a vínculo when data is returned", async () => {
    listMock.mockResolvedValue([vinculoAlberto]);
    render(<VinculosBlock clienteId={10} />);
    await waitFor(() => expect(screen.getByText("Alberto Garcia")).toBeInTheDocument());
    expect(screen.getByText("· administrador")).toBeInTheDocument();
  });

  it("adds a vínculo through the form", async () => {
    listMock.mockResolvedValueOnce([]).mockResolvedValueOnce([vinculoAlberto]);
    addMock.mockResolvedValue(vinculoAlberto);
    const user = userEvent.setup();
    render(<VinculosBlock clienteId={10} />);
    await waitFor(() => expect(screen.getByText("Sin vínculos todavía.")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Rol"), "Administrador");
    await user.type(screen.getByLabelText("Nombre"), "Alberto Garcia");
    await user.click(screen.getByRole("button", { name: "Añadir vínculo" }));

    await waitFor(() => expect(addMock).toHaveBeenCalledTimes(1));
    expect(addMock).toHaveBeenCalledWith(
      10,
      expect.objectContaining({ rol: "Administrador", nombre: "Alberto Garcia" })
    );
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
  });

  it("deletes a vínculo after confirming in the dialog", async () => {
    listMock.mockResolvedValueOnce([vinculoAlberto]).mockResolvedValueOnce([]);
    deleteMock.mockResolvedValue({ deleted: true });
    const user = userEvent.setup();
    render(<VinculosBlock clienteId={10} />);
    await waitFor(() => expect(screen.getByText("Alberto Garcia")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Eliminar" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Eliminar vínculo")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Eliminar" }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(10, vinculoAlberto.id));
  });
});
