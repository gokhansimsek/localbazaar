import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceChart } from "./PriceChart";
import type { HistoryPoint } from "@/lib/api";

// recharts uses ResponsiveContainer with dimensions from the DOM, which jsdom does not
// provide. Stub it to a fixed-size div so child charts can render.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 400 }}>{children}</div>
    ),
  };
});

describe("PriceChart", () => {
  it("shows an empty-state when there are no points", () => {
    render(<PriceChart points={[]} />);
    expect(screen.getByText(/yeterli tarihsel veri yok/i)).toBeInTheDocument();
  });

  it("hides the empty-state when at least one point exists", () => {
    const points: HistoryPoint[] = [
      {
        bulletin_date: "2026-05-11",
        city_slug: "national",
        product_variety: null,
        product_category: "Geleneksel/Konvansiyonel",
        average_price: "18.4",
        unit_name: "Kg",
        interpolated: false,
      },
    ];
    render(<PriceChart points={points} />);
    expect(screen.queryByText(/yeterli tarihsel veri yok/i)).not.toBeInTheDocument();
  });

  it("renders without crashing for multi-city data", () => {
    const points: HistoryPoint[] = [
      {
        bulletin_date: "2026-05-10",
        city_slug: "national",
        product_variety: null,
        product_category: "Geleneksel/Konvansiyonel",
        average_price: "17.5",
        unit_name: "Kg",
        interpolated: false,
      },
      {
        bulletin_date: "2026-05-11",
        city_slug: "national",
        product_variety: null,
        product_category: "Geleneksel/Konvansiyonel",
        average_price: "18.4",
        unit_name: "Kg",
        interpolated: false,
      },
      {
        bulletin_date: "2026-05-10",
        city_slug: "istanbul",
        product_variety: null,
        product_category: "Geleneksel/Konvansiyonel",
        average_price: "19.0",
        unit_name: "Kg",
        interpolated: false,
      },
      {
        bulletin_date: "2026-05-11",
        city_slug: "istanbul",
        product_variety: null,
        product_category: "Geleneksel/Konvansiyonel",
        average_price: "19.5",
        unit_name: "Kg",
        interpolated: false,
      },
    ];
    render(<PriceChart points={points} />);
    // Behavioral contract: the empty-state is NOT shown when data exists.
    expect(screen.queryByText(/yeterli tarihsel veri yok/i)).not.toBeInTheDocument();
  });
});
