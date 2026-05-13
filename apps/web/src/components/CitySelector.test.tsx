import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CitySelector } from "./CitySelector";
import type { City } from "@/lib/api";

const cities: City[] = [
  { slug: "national", name: "National", source_type: "hal_gov_tr", enabled: true },
  { slug: "istanbul", name: "Istanbul", source_type: "city_site", enabled: true },
  { slug: "ankara", name: "Ankara", source_type: "city_site", enabled: true },
];

describe("CitySelector", () => {
  it("renders one button per city", () => {
    render(<CitySelector cities={cities} value="national" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "National" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Istanbul" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ankara" })).toBeInTheDocument();
  });

  it("invokes onChange with the clicked slug", async () => {
    const handle = vi.fn();
    const user = userEvent.setup();
    render(<CitySelector cities={cities} value="national" onChange={handle} />);
    await user.click(screen.getByRole("button", { name: "Istanbul" }));
    expect(handle).toHaveBeenCalledWith("istanbul");
  });

  it("renders empty when no cities are supplied", () => {
    const { container } = render(<CitySelector cities={[]} value="" onChange={() => {}} />);
    expect(container.querySelectorAll("button").length).toBe(0);
  });
});
