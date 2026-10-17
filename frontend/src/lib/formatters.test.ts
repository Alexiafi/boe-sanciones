import { describe, expect, it } from "vitest";
import { enlaceExterno, formatCurrency, formatDate, formatDateTime, isoADateTimeLocal, localADateTimeIso } from "./formatters";

describe("formatCurrency", () => {
  it("formats a number as EUR currency", () => {
    expect(formatCurrency(1234.5)).toContain("1234,50".slice(0, 4));
    expect(formatCurrency(1234.5)).toMatch(/€/);
  });

  it("returns an em dash for null/undefined", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatCurrency(undefined)).toBe("—");
  });
});

describe("formatDate", () => {
  it("formats an ISO date as dd/mm/yyyy", () => {
    expect(formatDate("2026-08-03")).toBe("03/08/2026");
  });

  it("returns an em dash for empty input", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate("")).toBe("—");
  });

  it("returns the raw string for unparseable input", () => {
    expect(formatDate("no-es-una-fecha")).toBe("no-es-una-fecha");
  });
});

describe("formatDateTime", () => {
  it("includes both date and time", () => {
    const result = formatDateTime("2026-08-03T10:30:00Z");
    expect(result).toContain("2026");
  });
});

describe("enlaceExterno", () => {
  it("only lets absolute http(s) URLs become a link", () => {
    expect(enlaceExterno("https://www.acme.es/contacto")).toBe("https://www.acme.es/contacto");
    expect(enlaceExterno("  http://acme.es  ")).toBe("http://acme.es");
  });

  it("rejects what would resolve against this app and 404", () => {
    // Real values that used to be rendered as <a href>: a BOE path and a free-text source.
    expect(enlaceExterno("/boe_n/dias/2026/10/01/not.php?id=BOE-N-2026-1")).toBeNull();
    expect(enlaceExterno("historico-local")).toBeNull();
    expect(enlaceExterno("javascript:alert(1)")).toBeNull();
    expect(enlaceExterno(null)).toBeNull();
    expect(enlaceExterno("")).toBeNull();
  });
});

describe("datetime-local helpers", () => {
  it("round-trips a local date-time through an ISO instant", () => {
    const local = "2026-10-05T09:30";
    const iso = localADateTimeIso(local);
    expect(iso).toMatch(/Z$/);
    expect(isoADateTimeLocal(iso)).toBe(local);
  });

  it("handles empty and invalid input", () => {
    expect(localADateTimeIso("")).toBeNull();
    expect(localADateTimeIso("nope")).toBeNull();
    expect(isoADateTimeLocal(null)).toBe("");
    expect(isoADateTimeLocal("nope")).toBe("");
  });
});
