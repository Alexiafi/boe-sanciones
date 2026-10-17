import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VinculosBlock } from "./VinculosBlock";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    clientes: {
      listVinculos: vi.fn(),
      addVinculo: vi.fn(),
      deleteVinculo: vi.fn(),
      convertirVinculo: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const listMock = api.clientes.listVinculos as unknown as ReturnType<typeof vi.fn>;
const addMock = api.clientes.addVinculo as unknown as ReturnType<typeof vi.fn>;
const deleteMock = api.clientes.deleteVinculo as unknown as ReturnType<typeof vi.fn>;
const convertirMock = api.clientes.convertirVinculo as unknown as ReturnType<typeof vi.fn>;

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
    convertirMock.mockReset();
    pushMock.mockReset();
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

  it("converts a vínculo into its own client after confirming, then opens the new ficha", async () => {
    const convertido = { ...vinculoAlberto, cliente_vinculado_id: 77 };
    listMock.mockResolvedValueOnce([vinculoAlberto]).mockResolvedValueOnce([convertido]);
    convertirMock.mockResolvedValue({
      created: true,
      cliente: { id: 77, codigo: "CLI-2026-0002", nombre_razon_social: "Alberto Garcia" },
      vinculo: convertido,
    });
    const onCambio = vi.fn();
    const user = userEvent.setup();
    render(<VinculosBlock clienteId={10} onCambio={onCambio} />);
    await waitFor(() => expect(screen.getByText("Alberto Garcia")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Convertir en cliente" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Convertir vínculo en cliente")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Crear ficha de cliente" }));

    await waitFor(() => expect(convertirMock).toHaveBeenCalledWith(10, vinculoAlberto.id));
    await waitFor(() => expect(onCambio).toHaveBeenCalled());
    expect(pushMock).toHaveBeenCalledWith("/clientes/77");
    await waitFor(() => expect(screen.getByRole("link", { name: "Ver ficha de cliente" })).toHaveAttribute("href", "/clientes/77"));
    expect(screen.queryByRole("button", { name: "Convertir en cliente" })).not.toBeInTheDocument();
  });

  it("offers only the ficha link for a vínculo that already has its own client", async () => {
    listMock.mockResolvedValue([{ ...vinculoAlberto, cliente_vinculado_id: 5 }]);
    render(<VinculosBlock clienteId={10} />);
    await waitFor(() => expect(screen.getByRole("link", { name: "Ver ficha de cliente" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Convertir en cliente" })).not.toBeInTheDocument();
  });
});
