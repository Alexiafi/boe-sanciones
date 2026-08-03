import { describe, expect, it } from "vitest";
import { formatCurrency, formatDate, formatDateTime } from "./formatters";

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
