"use client";

import { useId, useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { ProductSummary } from "@/lib/api";
import { cn } from "@/lib/cn";

type Props = {
  products: ProductSummary[];
  value: string;
  onChange: (productName: string) => void;
};

/**
 * Searchable product picker. Filters the list as the user types and shows
 * each product's most recent price as a hint.
 */
export function ProductPicker({ products, value, onChange }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const listId = useId();

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr-TR");
    if (!needle) return products.slice(0, 50);
    return products
      .filter((p) => p.product_name.toLocaleLowerCase("tr-TR").includes(needle))
      .slice(0, 50);
  }, [products, query]);

  return (
    <div className="relative w-full max-w-md">
      <label htmlFor={listId} className="text-xs text-ink-muted">
        Ürün
      </label>
      <div className="relative mt-1">
        <Search
          size={16}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint"
        />
        <input
          id={listId}
          type="text"
          value={query || value}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            // Allow click handler to fire before closing.
            setTimeout(() => setOpen(false), 150);
          }}
          placeholder="Ürün adı yazın veya listeden seçin…"
          className="w-full rounded-xl border border-surface-border bg-white py-2 pl-9 pr-3 text-sm outline-none transition-all focus:border-indigo-400 focus:shadow-ring"
        />
      </div>

      {open && filtered.length > 0 && (
        <ul
          role="listbox"
          className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-surface-border bg-white shadow-soft"
        >
          {filtered.map((p) => (
            <li key={p.product_name}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange(p.product_name);
                  setQuery("");
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-indigo-50",
                  p.product_name === value && "bg-indigo-50/60 font-medium text-indigo-700",
                )}
              >
                <span>{p.product_name}</span>
                <span className="text-xs text-ink-faint">
                  {p.unit_name} · son {p.latest_bulletin_date}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
