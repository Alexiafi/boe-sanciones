import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AccionItem } from "./AccionItem";
import type { AccionAgendada } from "@/lib/types";

function accion(overrides: Partial<AccionAgendada> = {}): AccionAgendada {
  return {
    id: 5, cliente_id: 1, tipo: "llamada", titulo: "Volver a llamar", fecha_programada: null, estado: "pendiente",
    notas: null, created_at: "2026-10-01T08:00:00Z", ...overrides,
  };
}

describe("AccionItem", () => {
  it("flags an overdue pending action", () => {
    render(<AccionItem accion={accion({ fecha_programada: "2020-01-01T09:00:00Z" })} onEstado={vi.fn()} onReprogramar={vi.fn()} />);
    expect(screen.getByText("Vencida")).toBeInTheDocument();
  });

  it("does not flag a future action or a finished one", () => {
    const futura = new Date(Date.now() + 3 * 86_400_000).toISOString();
    const { rerender } = render(<AccionItem accion={accion({ fecha_programada: futura })} onEstado={vi.fn()} onReprogramar={vi.fn()} />);
    expect(screen.queryByText("Vencida")).not.toBeInTheDocument();
    rerender(<AccionItem accion={accion({ fecha_programada: "2020-01-01T09:00:00Z", estado: "hecha" })} onEstado={vi.fn()} onReprogramar={vi.fn()} />);
    expect(screen.queryByText("Vencida")).not.toBeInTheDocument();
    expect(screen.queryByText("Marcar hecha")).not.toBeInTheDocument();
  });

  it("marks done / cancelled", async () => {
    const user = userEvent.setup();
    const onEstado = vi.fn();
    const a = accion();
    render(<AccionItem accion={a} onEstado={onEstado} onReprogramar={vi.fn()} />);
    await user.click(screen.getByText("Marcar hecha"));
    expect(onEstado).toHaveBeenCalledWith(a, "hecha");
    await user.click(screen.getByText("Cancelar"));
    expect(onEstado).toHaveBeenLastCalledWith(a, "cancelada");
  });

  it("reschedules with the chosen local date-time", async () => {
    const user = userEvent.setup();
    const onReprogramar = vi.fn();
    const a = accion();
    render(<AccionItem accion={a} onEstado={vi.fn()} onReprogramar={onReprogramar} />);
    await user.click(screen.getByText("Cambiar fecha"));
    const input = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    await user.type(input, "2026-10-05T09:30");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(onReprogramar).toHaveBeenCalledWith(a, "2026-10-05T09:30");
  });
});
