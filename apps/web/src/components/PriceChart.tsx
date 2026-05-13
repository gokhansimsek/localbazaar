"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import type { HistoryPoint } from "@/lib/api";
import { formatDate, formatPrice } from "@/lib/format";

type Props = {
  points: HistoryPoint[];
  /**
   * Optional slug → display name map (e.g. ``{ national: "Ulusal" }``).
   * Missing slugs fall back to the slug itself.
   */
  cityNames?: Record<string, string>;
};

const SERIES_COLORS = [
  "#635BFF", // indigo (brand)
  "#00D4FF", // sky
  "#FF7AB6", // pink
  "#A78BFA", // violet
  "#0FB67A", // success green
  "#F59E0B", // amber
  "#3DDC97", // mint
  "#EF4444", // red
  "#06B6D4", // cyan
  "#F97316", // orange
];

type Series = { key: string; label: string };

/**
 * Pivots history points into a chart-friendly shape: one row per bulletin_date,
 * one numeric column per distinct (city_slug, product_category, product_variety) triple.
 * Different production methods (categories) and varieties stay on their own lines
 * instead of being silently averaged together.
 */
function pivot(
  points: HistoryPoint[],
  cityNames: Record<string, string> | undefined,
): {
  rows: Array<Record<string, number | string>>;
  series: Series[];
} {
  const seriesByKey = new Map<string, Series>();
  const byDate = new Map<string, Record<string, number | string>>();

  for (const p of points) {
    const key = seriesKey(p);
    if (!seriesByKey.has(key)) {
      seriesByKey.set(key, { key, label: seriesLabel(p, cityNames, points) });
    }
    const r = byDate.get(p.bulletin_date) ?? { bulletin_date: p.bulletin_date };
    r[key] = Number(p.average_price);
    byDate.set(p.bulletin_date, r);
  }

  const rows = Array.from(byDate.values()).sort((a, b) =>
    String(a.bulletin_date).localeCompare(String(b.bulletin_date)),
  );
  const series = Array.from(seriesByKey.values()).sort((a, b) => a.label.localeCompare(b.label));
  return { rows, series };
}

function seriesKey(p: HistoryPoint): string {
  return [p.city_slug, p.product_category ?? "", p.product_variety ?? ""].join("|");
}

/**
 * Compose a human-readable legend label.
 *
 * - Always shows the category (production method) when present.
 * - Adds the variety only when more than one distinct variety appears in the
 *   data — for single-variety products (e.g. ACUR) the variety just repeats
 *   the product name and clutters the legend.
 * - Adds the city name only when more than one city contributes to the chart,
 *   so single-city charts stay uncluttered.
 */
function seriesLabel(
  p: HistoryPoint,
  cityNames: Record<string, string> | undefined,
  allPoints: HistoryPoint[],
): string {
  const parts: string[] = [];
  if (p.product_category) parts.push(p.product_category);
  const distinctVarieties = new Set(
    allPoints.map((q) => q.product_variety).filter((v): v is string => Boolean(v)),
  );
  if (p.product_variety && distinctVarieties.size > 1) {
    parts.push(p.product_variety);
  }
  const distinctCities = new Set(allPoints.map((q) => q.city_slug));
  if (distinctCities.size > 1) {
    parts.push(cityNames?.[p.city_slug] ?? p.city_slug);
  }
  return parts.length > 0 ? parts.join(" · ") : (cityNames?.[p.city_slug] ?? p.city_slug);
}

export function PriceChart({ points, cityNames }: Props) {
  const { rows, series } = useMemo(() => pivot(points, cityNames), [points, cityNames]);

  if (rows.length === 0) {
    return (
      <div className="card flex h-72 items-center justify-center text-ink-muted">
        Bu ürün için yeterli tarihsel veri yok.
      </div>
    );
  }

  return (
    <div className="card p-6">
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
            <CartesianGrid stroke="#E3E8EF" vertical={false} />
            <XAxis
              dataKey="bulletin_date"
              tickFormatter={(v: string) => formatDate(v)}
              tick={{ fill: "#697386", fontSize: 12 }}
              tickMargin={8}
              stroke="#E3E8EF"
            />
            <YAxis
              tick={{ fill: "#697386", fontSize: 12 }}
              tickFormatter={(v: number) => `${v.toLocaleString("tr-TR")} ₺`}
              stroke="#E3E8EF"
              width={70}
            />
            <Tooltip
              labelFormatter={(label: string) => formatDate(label)}
              formatter={(value: number, name: string) => [formatPrice(value), name]}
              contentStyle={{
                borderRadius: 12,
                border: "1px solid #E3E8EF",
                boxShadow: "0 4px 24px -8px rgba(50, 50, 93, 0.12)",
                fontSize: 13,
              }}
            />
            <Legend
              iconType="circle"
              wrapperStyle={{ fontSize: 12, paddingTop: 8, color: "#425466" }}
            />
            {series.map((s, i) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
