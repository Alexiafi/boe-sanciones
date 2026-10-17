import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    sanciones: {
      create: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";
import NuevaMultaPage from "./page";

const createMock = api.sanciones.create as unknown as ReturnType<typeof vi.fn>;

describe("NuevaMultaPage", () => {
  beforeEach(() => {
    createMock.mockReset();
    push.mockReset();
  });

  it("sends the form to the alta manual endpoint", async () => {
    createMock.mockResolvedValue({ id: 42, cliente_id: null });
    const user = userEvent.setup();
    render(<NuevaMultaPage />);

    await user.type(screen.getByLabelText(/Nombre \/ razón social/i), "Construcciones Levante S.A.");
    await user.type(screen.getByLabelText(/CIF \/ NIF/i), "A12345678");
    await user.click(screen.getByRole("button", { name: "Guardar multa" }));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock.mock.calls[0][0]).toMatchObject({
      nombre: "Construcciones Levante S.A.",
      identificador: "A12345678",
      crear_cliente: false,
    });
    expect(push).toHaveBeenCalledWith("/sanciones/42");
  });
});
