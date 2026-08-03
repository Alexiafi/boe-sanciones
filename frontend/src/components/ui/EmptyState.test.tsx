import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";

describe("EmptyState", () => {
  it("renders title and optional description", () => {
    render(<EmptyState title="Sin resultados" description="Prueba a cambiar los filtros." />);
    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
    expect(screen.getByText("Prueba a cambiar los filtros.")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("announces the error via role=alert", () => {
    render(<ErrorState message="No se pudo conectar." />);
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo conectar.");
  });

  it("calls onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} />);
    screen.getByRole("button", { name: "Reintentar" }).click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders no retry button when onRetry is not provided", () => {
    render(<ErrorState />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
