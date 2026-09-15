"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import type { PriceRow } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/cn";

type SortKey =
  | "product_name"
  | "product_variety"
  | "product_category"
  | "average_price"
  | "unit_name";

type SortDir = "asc" | "desc";

type Props = {
  rows: PriceRow[];
  pageSize?: number;
};

const DEFAULT_PAGE_SIZE = 25;

export function PriceTable({ rows, pageSize = DEFAULT_PAGE_SIZE }: Props) {
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("product_name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase("tr-TR");
    const data = needle
      ? rows.filter((r) =>
          [r.product_name, r.product_variety ?? "", r.product_category ?? ""]
            .join(" ")
            .toLocaleLowerCase("tr-TR")
            .includes(needle),
        )
      : rows;

    const sorted = [...data].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp = compare(av, bv);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [rows, q, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));

  // Reset to page 1 whenever the filter / sort / source data changes.
  useEffect(() => {
    setPage(1);
  }, [q, sortKey, sortDir, rows]);

  const pageRows = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize],
  );

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-surface-border px-5 py-4">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            placeholder="Ürün ara…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="w-72 max-w-full rounded-xl border border-surface-border bg-surface-subtle py-2 pl-9 pr-3 text-sm outline-none transition-all focus:border-crate-400 focus:shadow-ring"
          />
        </div>
        <span className="text-xs text-ink-muted">{filtered.length} kayıt</span>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="bg-surface-subtle text-xs font-semibold text-ink-muted">
              <Th
                label="Ürün"
                k="product_name"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggleSort}
              />
              <Th
                label="Cinsi"
                k="product_variety"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggleSort}
              />
              <Th
                label="Türü"
                k="product_category"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggleSort}
              />
              <Th
                label="Ortalama Fiyat"
                k="average_price"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggleSort}
                align="right"
              />
              <Th
                label="Birim"
                k="unit_name"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggleSort}
              />
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, i) => (
              <tr
                key={`${r.product_name}-${r.product_variety}-${r.product_category}-${r.unit_name}-${i}`}
                className="data-row border-t border-surface-border/60"
              >
                <td className="px-5 py-3">
                  <Link
                    href={`/products/${encodeURIComponent(r.product_name)}`}
                    className="font-medium text-ink hover:text-crate-700"
                  >
                    {r.product_name}
                  </Link>
                </td>
                <td className="px-5 py-3 text-ink-soft">{r.product_variety ?? "—"}</td>
                <td className="px-5 py-3">
                  {r.product_category ? (
                    <span className="chip">{r.product_category}</span>
                  ) : (
                    <span className="text-ink-faint">—</span>
                  )}
                </td>
                <td className="px-5 py-3 text-right font-semibold tabular-nums text-ink">
                  {formatPrice(r.average_price)}
                </td>
                <td className="px-5 py-3 text-ink-soft">{r.unit_name}</td>
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-10 text-center text-ink-muted">
                  Bu güne ait kayıt bulunamadı.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onChange={setPage}
          totalRows={filtered.length}
          pageSize={pageSize}
        />
      )}
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  onChange,
  totalRows,
  pageSize,
}: {
  page: number;
  totalPages: number;
  onChange: (n: number) => void;
  totalRows: number;
  pageSize: number;
}) {
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalRows);
  const visible = pageWindow(page, totalPages);

  return (
    <div className="flex items-center justify-between border-t border-surface-border px-5 py-3 text-xs text-ink-muted">
      <span>
        {start}–{end} / {totalRows}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-40"
          onClick={() => onChange(page - 1)}
          disabled={page === 1}
          aria-label="Önceki sayfa"
        >
          <ChevronLeft size={14} />
        </button>
        {visible.map((n, idx) =>
          n === "…" ? (
            <span key={`gap-${idx}`} className="px-2 text-ink-faint">
              …
            </span>
          ) : (
            <button
              key={n}
              type="button"
              onClick={() => onChange(n)}
              className={cn(
                "min-w-8 rounded-lg px-2 py-1 font-medium transition-colors",
                n === page ? "bg-ink text-surface-subtle" : "text-ink-soft hover:bg-surface-muted",
              )}
            >
              {n}
            </button>
          ),
        )}
        <button
          type="button"
          className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-40"
          onClick={() => onChange(page + 1)}
          disabled={page === totalPages}
          aria-label="Sonraki sayfa"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

function pageWindow(page: number, totalPages: number): Array<number | "…"> {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const items: Array<number | "…"> = [1];
  const left = Math.max(2, page - 1);
  const right = Math.min(totalPages - 1, page + 1);
  if (left > 2) items.push("…");
  for (let i = left; i <= right; i++) items.push(i);
  if (right < totalPages - 1) items.push("…");
  items.push(totalPages);
  return items;
}

function Th({
  label,
  k,
  sortKey,
  sortDir,
  onClick,
  align = "left",
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === k;
  return (
    <th
      className={cn(
        "cursor-pointer select-none px-5 py-3 font-medium hover:text-ink",
        align === "right" ? "text-right" : "text-left",
      )}
      onClick={() => onClick(k)}
    >
      <span
        className={cn("inline-flex items-center gap-1", align === "right" && "w-full justify-end")}
      >
        {label}
        <ArrowUpDown
          size={12}
          className={cn(
            "transition-opacity",
            active ? "text-crate-500 opacity-100" : "opacity-30",
            active && sortDir === "desc" && "rotate-180",
          )}
        />
      </span>
    </th>
  );
}

function compare(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const na = typeof a === "number" ? a : Number(a);
  const nb = typeof b === "number" ? b : Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb) && (typeof a !== "string" || /^[\d.,-]+$/.test(a))) {
    return na - nb;
  }
  return String(a).localeCompare(String(b), "tr-TR");
}
