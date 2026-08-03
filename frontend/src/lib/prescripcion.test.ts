import { describe, expect, it } from "vitest";
import { prescripcionTier } from "./prescripcion";

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

describe("prescripcionTier", () => {
  it("marks a recent BOE document as reciente", () => {
    expect(prescripcionTier(daysAgoIso(10), "boe")).toBe("reciente");
  });

  it("marks an old BOE document (over 4 years) as archivado", () => {
    expect(prescripcionTier(daysAgoIso(365 * 5), "boe")).toBe("archivado");
  });

  it("marks a BOE document between 180 days and 4 years as proximo", () => {
    expect(prescripcionTier(daysAgoIso(300), "boe")).toBe("proximo");
  });

  it("marks a TEU document close to the 90-day public window edge as urgente", () => {
    expect(prescripcionTier(daysAgoIso(80), "teu")).toBe("urgente");
  });

  it("marks a TEU document approaching the window as proximo", () => {
    expect(prescripcionTier(daysAgoIso(65), "teu")).toBe("proximo");
  });

  it("marks a fresh TEU document as reciente", () => {
    expect(prescripcionTier(daysAgoIso(5), "teu")).toBe("reciente");
  });
});
