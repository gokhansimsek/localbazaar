"use client";

import { useEffect, useMemo, useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { AdSlot } from "@/components/AdSlot";
import { MultiSelect } from "@/components/MultiSelect";
import { PriceChart, listSeries } from "@/components/PriceChart";
import { ProductPicker } from "@/components/ProductPicker";
import {
  listCities,
  listProducts,
  productHistory,
  type City,
  type HistoryPoint,
  type ProductSummary,
} from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/cn";

type Granularity = "daily" | "weekly" | "monthly";

type RangeDef = {
  key: string;
  label: string;
  /** ``"today"`` snaps to the latest day; ``"all"`` uses the full window; a number is the lookback in days. */
  days: number | "today" | "all";
  granularity: Granularity;
};

/**
 * Range buckets shown as stat cards. Click one to filter the chart below.
 * Granularity controls how the filtered points are bucketed before plotting:
 * short windows show daily points, medium windows roll up to weekly, and the
 * full-history view rolls up to monthly so a year+ of data stays readable.
 */
const RANGES: RangeDef[] = [
  { key: "today", label: "Bugün", days: "today", granularity: "daily" },
  { key: "1w", label: "Son hafta", days: 7, granularity: "daily" },
  { key: "1m", label: "Son ay", days: 30, granularity: "daily" },
  { key: "3m", label: "Son 3 ay", days: 90, granularity: "weekly" },
  { key: "1y", label: "Son yıl", days: 365, granularity: "weekly" },
  { key: "all", label: "Tümü", days: "all", granularity: "monthly" },
];

const DEFAULT_RANGE_KEY = "1m";

export default function TrendsPage() {
  const [products, setProducts] = useState<ProductSummary[]>([]);
  const [cityNames, setCityNames] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string>("");
  // dailyPoints powers the stat-card deltas across every range; it's the full
  // unaggregated history fetched once per product change.
  const [dailyPoints, setDailyPoints] = useState<HistoryPoint[]>([]);
  // chartPoints is the server-bucketed + regression-filled series for the
  // active range; it's exactly what the chart plots.
  const [chartPoints, setChartPoints] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeRangeKey, setActiveRangeKey] = useState<string>(DEFAULT_RANGE_KEY);
  // Series the user wants drawn (keys of city × category × variety lines).
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    listProducts()
      .then((p) => {
        setProducts(p);
        if (p.length > 0 && !selected) setSelected(p[0].product_name);
      })
      .catch((e) => setError(String(e)));
    listCities()
      .then((cs: City[]) => setCityNames(Object.fromEntries(cs.map((c) => [c.slug, c.name]))))
      .catch(() => {
        /* legend will fall back to slugs if cities fail to load */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    productHistory(selected)
      .then(setDailyPoints)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [selected]);

  const activeRange = RANGES.find((r) => r.key === activeRangeKey) ?? RANGES[2];

  // Fetch the chart series from the server for the active range: it buckets to
  // the target granularity and fills gaps with a per-series least-squares
  // regression, so the client just plots what comes back. dailyPoints (full,
  // unfilled) still drives the stat cards below.
  useEffect(() => {
    if (!selected) return;
    // Wait for the full history to land so range bounds anchor on the real
    // latest date instead of firing an unbounded full-history fill first.
    if (dailyPoints.length === 0) return;
    const { from, to } = rangeBounds(dailyPoints, activeRange);
    const opts: Parameters<typeof productHistory>[1] = {
      granularity: activeRange.granularity,
      fill: true,
    };
    if (from) opts.from = from;
    if (to) opts.to = to;
    productHistory(selected, opts)
      .then(setChartPoints)
      .catch((e) => setError(String(e)));
  }, [selected, activeRange, dailyPoints]);

  const buckets = useMemo(() => computeBuckets(dailyPoints), [dailyPoints]);
  const summary = products.find((p) => p.product_name === selected);

  // The distinct series available for the current product/range, used to build
  // the multiselect options.
  const chartSeries = useMemo(() => listSeries(chartPoints, cityNames), [chartPoints, cityNames]);

  // Reset the filter to "none selected" whenever the available series change
  // (e.g. a different product is picked), so the user opts into the halls they
  // want. Keyed on the joined keys so it only fires on a real change.
  const seriesSig = chartSeries.map((s) => s.key).join("|");
  useEffect(() => {
    setVisibleKeys(new Set());
  }, [seriesSig]);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <span className="chip">Fiyat İstatistikleri</span>
        <h1 className="text-3xl font-semibold tracking-tight lg:text-4xl">Fiyat İstatistikleri</h1>
        <p className="max-w-2xl text-ink-soft">
          Bir ürün seçin; bugünden son bir yıla kadar farklı zaman aralıklarında ortalama fiyat
          değişimini görün. Aşağıdaki kartlardan birini seçerek grafiği filtreleyin.
        </p>
      </header>

      <section className="flex flex-col gap-4 lg:flex-row lg:items-end">
        <ProductPicker products={products} value={selected} onChange={setSelected} />
        {chartSeries.length > 0 && (
          <MultiSelect
            label="Hal"
            className="w-full lg:w-64"
            options={chartSeries.map((s) => ({ value: s.key, label: s.label }))}
            selected={visibleKeys}
            onChange={setVisibleKeys}
          />
        )}
        {summary && (
          <div className="text-xs text-ink-muted">
            Birim: <span className="font-medium text-ink">{summary.unit_name}</span> · Son bülten:{" "}
            <span className="font-medium text-ink">{summary.latest_bulletin_date}</span>
          </div>
        )}
      </section>

      {error && (
        <div className="card p-4 text-sm text-ink-soft">
          Veriler şu anda görüntülenemiyor. Birkaç dakika sonra tekrar deneyin.
        </div>
      )}

      {loading && <div className="card p-12 text-center text-ink-muted">Yükleniyor…</div>}

      {!loading && selected && (
        <>
          <section
            className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6"
            role="tablist"
            aria-label="Zaman aralığı"
          >
            {RANGES.map((r) => (
              <BucketCard
                key={r.key}
                range={r}
                bucket={buckets[r.key]}
                active={r.key === activeRangeKey}
                onSelect={() => setActiveRangeKey(r.key)}
              />
            ))}
          </section>

          <section>
            <h2 className="mb-3 flex items-center justify-between text-sm font-medium text-ink-muted">
              <span>
                Tarihsel seri · <span className="text-ink">{activeRange.label}</span>
              </span>
              <span className="text-[11px] uppercase tracking-wide text-ink-faint">
                {granularityLabel(activeRange.granularity)} · eksik noktalar otomatik olarak
                doldurulmuştur
              </span>
            </h2>
            {visibleKeys.size === 0 ? (
              <div className="card flex h-72 items-center justify-center text-center text-sm text-ink-muted">
                Grafiği görüntülemek için yukarıdan en az bir hal seçin.
              </div>
            ) : (
              <PriceChart points={chartPoints} cityNames={cityNames} visibleKeys={visibleKeys} />
            )}
          </section>

          {process.env.NEXT_PUBLIC_ADSENSE_TRENDS_SLOT ? (
            <section aria-label="Reklam alanı" className="mt-4">
              <AdSlot slot={process.env.NEXT_PUBLIC_ADSENSE_TRENDS_SLOT} />
            </section>
          ) : null}
        </>
      )}

      {!loading && !selected && products.length === 0 && (
        <div className="card p-12 text-center text-ink-muted">
          Henüz ürün verisi yok. Önce scrape&apos;i çalıştırın.
        </div>
      )}
    </div>
  );
}

type Bucket = {
  latest: number | null;
  start: number | null;
  deltaPct: number | null;
  min: number | null;
  max: number | null;
  samples: number;
};

function computeBuckets(points: HistoryPoint[]): Record<string, Bucket> {
  const result: Record<string, Bucket> = {};
  if (points.length === 0) {
    for (const r of RANGES) result[r.key] = emptyBucket();
    return result;
  }
  const sorted = [...points].sort((a, b) => a.bulletin_date.localeCompare(b.bulletin_date));
  const latestDate = new Date(sorted[sorted.length - 1].bulletin_date);

  for (const r of RANGES) {
    const inWindow = filterByRange(sorted, latestDate, r.days);
    result[r.key] = summarize(inWindow);
  }
  return result;
}

function filterByRange(
  sorted: HistoryPoint[],
  latestDate: Date,
  days: number | "today" | "all",
): HistoryPoint[] {
  if (days === "all") return sorted;
  if (days === "today") {
    const iso = sorted[sorted.length - 1].bulletin_date;
    return sorted.filter((p) => p.bulletin_date === iso);
  }
  const from = new Date(latestDate);
  from.setDate(from.getDate() - days);
  const fromIso = from.toISOString().slice(0, 10);
  return sorted.filter((p) => p.bulletin_date >= fromIso);
}

function summarize(rows: HistoryPoint[]): Bucket {
  if (rows.length === 0) return emptyBucket();
  // Average all variants (variety × category) per day so the headline stat
  // does not arbitrarily pick whichever variant sorts last.
  const byDate = new Map<string, number[]>();
  for (const p of rows) {
    const n = Number(p.average_price);
    if (!Number.isFinite(n)) continue;
    const arr = byDate.get(p.bulletin_date) ?? [];
    arr.push(n);
    byDate.set(p.bulletin_date, arr);
  }
  const dailyAvgs = Array.from(byDate.entries())
    .map(([d, arr]) => ({ d, avg: arr.reduce((s, n) => s + n, 0) / arr.length }))
    .sort((a, b) => a.d.localeCompare(b.d));
  if (dailyAvgs.length === 0) return emptyBucket();
  const latest = dailyAvgs[dailyAvgs.length - 1].avg;
  const start = dailyAvgs[0].avg;
  const deltaPct = start === 0 ? 0 : ((latest - start) / start) * 100;
  const allPrices = Array.from(byDate.values()).flat();
  return {
    latest,
    start,
    deltaPct,
    min: Math.min(...allPrices),
    max: Math.max(...allPrices),
    samples: rows.length,
  };
}

function emptyBucket(): Bucket {
  return { latest: null, start: null, deltaPct: null, min: null, max: null, samples: 0 };
}

/**
 * Compute the inclusive ``{ from, to }`` ISO bounds for the active range,
 * anchored on the latest bulletin date in ``daily`` (so the window tracks the
 * actual data, not the wall clock). ``"all"`` returns no bounds (full history);
 * ``"today"`` collapses to the latest day; numeric ranges look back ``days``
 * from the latest date. The server uses these to bucket and regression-fill.
 */
function rangeBounds(daily: HistoryPoint[], range: RangeDef): { from?: string; to?: string } {
  if (daily.length === 0) return {};
  const sorted = [...daily].sort((a, b) => a.bulletin_date.localeCompare(b.bulletin_date));
  const latestIso = sorted[sorted.length - 1].bulletin_date;
  if (range.days === "all") return {};
  if (range.days === "today") return { from: latestIso, to: latestIso };
  const from = new Date(latestIso + "T00:00:00Z");
  from.setUTCDate(from.getUTCDate() - range.days);
  return { from: from.toISOString().slice(0, 10), to: latestIso };
}

function granularityLabel(g: Granularity): string {
  switch (g) {
    case "daily":
      return "Günlük";
    case "weekly":
      return "Haftalık";
    case "monthly":
      return "Aylık";
  }
}

function BucketCard({
  range,
  bucket,
  active,
  onSelect,
}: {
  range: RangeDef;
  bucket: Bucket | undefined;
  active: boolean;
  onSelect: () => void;
}) {
  const hasData = bucket && bucket.samples > 0;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onSelect}
      className={cn(
        "card focus-visible:ring-brand p-4 text-left transition focus:outline-none focus-visible:ring-2",
        active
          ? "border-brand bg-brand/5 ring-brand/40 ring-1"
          : "hover:border-ink-faint hover:bg-ink-faint/5",
      )}
    >
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-ink-muted">{range.label}</div>
        {active && (
          <span className="bg-brand/10 text-brand rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">
            seçili
          </span>
        )}
      </div>
      {hasData ? (
        <>
          <div className="mt-1 text-xl font-semibold tabular-nums">
            {formatPrice(bucket!.latest ?? 0)}
          </div>
          {bucket!.samples > 1 && Number.isFinite(bucket!.deltaPct) && (
            <div
              className={cn(
                "mt-1 inline-flex items-center gap-1 text-xs font-medium",
                (bucket!.deltaPct ?? 0) >= 0 ? "stat-up" : "stat-down",
              )}
            >
              {(bucket!.deltaPct ?? 0) >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {`${(bucket!.deltaPct ?? 0) >= 0 ? "+" : ""}${(bucket!.deltaPct ?? 0).toFixed(2)} %`}
            </div>
          )}
          <div className="mt-2 text-[10px] uppercase tracking-wide text-ink-faint">
            {bucket!.samples} kayıt
          </div>
          {bucket!.min !== null && bucket!.max !== null && bucket!.samples > 1 && (
            <div className="mt-0.5 text-[11px] text-ink-muted">
              {formatPrice(bucket!.min)} – {formatPrice(bucket!.max)}
            </div>
          )}
        </>
      ) : (
        <div className="mt-2 text-sm text-ink-faint">Veri yok</div>
      )}
    </button>
  );
}
