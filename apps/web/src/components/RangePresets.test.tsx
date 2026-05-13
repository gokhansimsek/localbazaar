import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RangePresets, rangeToFromDate } from "./RangePresets";

describe("RangePresets component", () => {
  it("renders the five preset buttons", () => {
    render(<RangePresets value="3M" onChange={() => {}} />);
    for (const label of ["1 Ay", "3 Ay", "6 Ay", "1 Yıl", "Tümü"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("invokes onChange with the clicked key", async () => {
    const handle = vi.fn();
    const user = userEvent.setup();
    render(<RangePresets value="3M" onChange={handle} />);
    await user.click(screen.getByRole("button", { name: "1 Yıl" }));
    expect(handle).toHaveBeenCalledWith("1Y");
  });
});

describe("rangeToFromDate", () => {
  it("returns undefined for ALL", () => {
    expect(rangeToFromDate("ALL")).toBeUndefined();
  });

  it("returns a date roughly one month back for 1M", () => {
    const out = rangeToFromDate("1M");
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const diffMs = Date.now() - new Date(out!).getTime();
    const diffDays = diffMs / (1000 * 60 * 60 * 24);
    expect(diffDays).toBeGreaterThan(25);
    expect(diffDays).toBeLessThan(40);
  });

  it("returns a date roughly one year back for 1Y", () => {
    const out = rangeToFromDate("1Y");
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const diffMs = Date.now() - new Date(out!).getTime();
    const diffDays = diffMs / (1000 * 60 * 60 * 24);
    expect(diffDays).toBeGreaterThan(350);
    expect(diffDays).toBeLessThan(380);
  });
});
