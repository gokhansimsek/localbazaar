import { describe, it, expect } from "vitest";
import { formatDate, formatInt, formatPrice, todayIso } from "./format";

describe("formatPrice", () => {
  it("formats a numeric value as TRY", () => {
    const out = formatPrice(18.4);
    expect(out).toMatch(/18[,.]40/);
    expect(out).toMatch(/₺|TRY|TL/);
  });

  it("formats a decimal string", () => {
    const out = formatPrice("125.00");
    expect(out).toMatch(/125/);
  });

  it("returns em-dash for NaN", () => {
    expect(formatPrice("not-a-number")).toBe("—");
  });
});

describe("formatInt", () => {
  it("formats integers with thousand separators", () => {
    expect(formatInt(1250)).toMatch(/1[.,]? ?\xA0?250|1\.?250/);
  });

  it("returns em-dash for null", () => {
    expect(formatInt(null)).toBe("—");
    expect(formatInt(undefined)).toBe("—");
  });
});

describe("formatDate", () => {
  it("formats an ISO date in tr-TR style", () => {
    const out = formatDate("2026-05-11");
    expect(out).toMatch(/11[./]05[./]2026/);
  });

  it("returns the input on a bogus date string", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("todayIso", () => {
  it("returns a YYYY-MM-DD slice", () => {
    expect(todayIso()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
