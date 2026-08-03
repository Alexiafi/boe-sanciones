import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Chip, EstadoChip } from "./Chip";

describe("Chip", () => {
  it("renders the given label", () => {
    render(<Chip label="Pendiente" />);
    expect(screen.getByText("Pendiente")).toBeInTheDocument();
  });
});

describe("EstadoChip", () => {
  it("maps a known estado_oportunidad value to its label", () => {
    render(<EstadoChip dominio="estado_oportunidad" valor="nueva" />);
    expect(screen.getByText("Nueva")).toBeInTheDocument();
  });

  it("falls back to the raw value for an unknown status", () => {
    render(<EstadoChip dominio="estado_cliente" valor="desconocido" />);
    expect(screen.getByText("desconocido")).toBeInTheDocument();
  });

  it("renders an em dash placeholder when the value is missing", () => {
    render(<EstadoChip dominio="contacto_estado" valor={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("maps every prescripcion tier used by /historial", () => {
    render(
      <>
        <EstadoChip dominio="prescripcion" valor="urgente" />
        <EstadoChip dominio="prescripcion" valor="proximo" />
        <EstadoChip dominio="prescripcion" valor="reciente" />
        <EstadoChip dominio="prescripcion" valor="archivado" />
      </>
    );
    expect(screen.getByText("Urgente")).toBeInTheDocument();
    expect(screen.getByText("Próximo vencimiento")).toBeInTheDocument();
    expect(screen.getByText("Reciente")).toBeInTheDocument();
    expect(screen.getByText("Archivado")).toBeInTheDocument();
  });
});
