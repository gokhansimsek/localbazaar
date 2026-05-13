import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PriceTable } from "./PriceTable";
import type { PriceRow } from "@/lib/api";

const rows: PriceRow[] = [
  {
    bulletin_date: "2026-05-11",
    product_name: "Domates",
    product_variety: "Salka",
    product_category: "Geleneksel/Konvansiyonel",
    average_price: "18.40",
    transaction_volume: 1250,
    unit_name: "Kg",
  },
  {
    bulletin_date: "2026-05-11",
    product_name: "Salatalık",
    product_variety: "Sera",
    product_category: "Geleneksel/Konvansiyonel",
    average_price: "11.75",
    transaction_volume: 820,
    unit_name: "Kg",
  },
  {
    bulletin_date: "2026-05-11",
    product_name: "Biber",
    product_variety: "Çarliston",
    product_category: "Organik Tarım",
    average_price: "29.50",
    transaction_volume: null,
    unit_name: "Kg",
  },
];

describe("PriceTable", () => {
  it("renders one row per data point", () => {
    render(<PriceTable rows={rows} />);
    expect(screen.getByText("Domates")).toBeInTheDocument();
    expect(screen.getByText("Salatalık")).toBeInTheDocument();
    expect(screen.getByText("Biber")).toBeInTheDocument();
    expect(screen.getByText("3 kayıt")).toBeInTheDocument();
  });

  it("renders an empty-state when there are no rows", () => {
    render(<PriceTable rows={[]} />);
    expect(screen.getByText(/kayıt bulunamadı/i)).toBeInTheDocument();
  });

  it("filters rows by product name as user types", async () => {
    const user = userEvent.setup();
    render(<PriceTable rows={rows} />);
    const input = screen.getByPlaceholderText(/Ürün ara/i);
    await user.type(input, "biber");
    expect(screen.queryByText("Domates")).not.toBeInTheDocument();
    expect(screen.getByText("Biber")).toBeInTheDocument();
    expect(screen.getByText("1 kayıt")).toBeInTheDocument();
  });

  it("links the product name to its detail page", () => {
    render(<PriceTable rows={rows} />);
    const link = screen.getByRole("link", { name: "Domates" });
    expect(link).toHaveAttribute("href", "/products/Domates");
  });

  it("default sort is ascending by product name", () => {
    render(<PriceTable rows={rows} />);
    const order = screen.getAllByRole("link").map((a) => a.textContent);
    expect(order).toEqual(["Biber", "Domates", "Salatalık"]);
  });

  it("toggles sort direction when clicking the active header again", () => {
    render(<PriceTable rows={rows} />);
    const productHeader = screen.getByText("Ürün");
    fireEvent.click(productHeader);
    let order = screen.getAllByRole("link").map((a) => a.textContent);
    expect(order).toEqual(["Salatalık", "Domates", "Biber"]);
    fireEvent.click(productHeader);
    order = screen.getAllByRole("link").map((a) => a.textContent);
    expect(order).toEqual(["Biber", "Domates", "Salatalık"]);
  });

  it("sorts numerically when sorting by Ortalama Fiyat", () => {
    render(<PriceTable rows={rows} />);
    fireEvent.click(screen.getByText("Ortalama Fiyat"));
    const order = screen.getAllByRole("link").map((a) => a.textContent);
    // 11.75, 18.40, 29.50 → Salatalık, Domates, Biber
    expect(order).toEqual(["Salatalık", "Domates", "Biber"]);
  });

  it("does not render a volume column", () => {
    render(<PriceTable rows={rows} />);
    expect(screen.queryByText(/Hacim|Volume|İşlem/i)).not.toBeInTheDocument();
  });

  it("hides pagination when all rows fit on one page", () => {
    render(<PriceTable rows={rows} pageSize={25} />);
    expect(screen.queryByLabelText("Önceki sayfa")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Sonraki sayfa")).not.toBeInTheDocument();
  });

  it("paginates when row count exceeds page size", async () => {
    const many: PriceRow[] = Array.from({ length: 7 }, (_, i) => ({
      bulletin_date: "2026-05-11",
      product_name: `Ürün-${String(i).padStart(2, "0")}`,
      product_variety: null,
      product_category: null,
      average_price: `${i}.00`,
      transaction_volume: null,
      unit_name: "Kg",
    }));
    render(<PriceTable rows={many} pageSize={3} />);

    // Page 1: first three products.
    expect(screen.getByText("Ürün-00")).toBeInTheDocument();
    expect(screen.getByText("Ürün-02")).toBeInTheDocument();
    expect(screen.queryByText("Ürün-03")).not.toBeInTheDocument();

    // Click "next" → page 2 should show the next three.
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Sonraki sayfa"));
    expect(screen.getByText("Ürün-03")).toBeInTheDocument();
    expect(screen.getByText("Ürün-05")).toBeInTheDocument();
    expect(screen.queryByText("Ürün-00")).not.toBeInTheDocument();

    // Page indicator should report the range.
    expect(screen.getByText(/4–6 \/ 7/)).toBeInTheDocument();
  });
});
