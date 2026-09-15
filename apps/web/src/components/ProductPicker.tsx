"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
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
 *
 * Keyboard support: Up/Down moves a roving highlight, Enter selects the
 * highlighted product, Escape closes the list.
 */
export function ProductPicker({ products, value, onChange }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const listId = useId();

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("tr-TR");
    if (!needle) return products.slice(0, 50);
    return products
      .filter((p) => p.product_name.toLocaleLowerCase("tr-TR").includes(needle))
      .slice(0, 50);
  }, [products, query]);

  useEffect(() => {
    setHighlight(0);
  }, [filtered]);

  useEffect(() => {
    if (open) optionRefs.current[highlight]?.scrollIntoView({ block: "nearest" });
  }, [open, highlight]);

  function select(productName: string): void {
    onChange(productName);
    setQuery("");
    setOpen(false);
  }

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
          onKeyDown={(e) => {
            if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
              setOpen(true);
              return;
            }
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setHighlight((h) => Math.min(h + 1, filtered.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHighlight((h) => Math.max(h - 1, 0));
            } else if (e.key === "Enter") {
              const p = filtered[highlight];
              if (open && p) {
                e.preventDefault();
                select(p.product_name);
              }
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          placeholder="Ürün adı yazın veya listeden seçin…"
          className="w-full rounded-xl border border-surface-border bg-white py-2 pl-9 pr-3 text-sm outline-none transition-all focus:border-crate-400 focus:shadow-ring"
        />
      </div>

      {open && filtered.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-surface-border bg-white shadow-soft"
        >
          {filtered.map((p, i) => (
            <li key={p.product_name}>
              <button
                ref={(el) => {
                  optionRefs.current[i] = el;
                }}
                type="button"
                role="option"
                aria-selected={p.product_name === value}
                onMouseEnter={() => setHighlight(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  select(p.product_name);
                }}
                className={cn(
                  "flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-surface-subtle",
                  p.product_name === value && "bg-surface-subtle font-semibold text-ink",
                  i === highlight && "bg-surface-muted",
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
