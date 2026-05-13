"use client";

import { useEffect, useMemo, useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { AdSlot } from "@/components/AdSlot";
import { PriceChart } from "@/components/PriceChart";
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
  // aggregatedPoints carries the pre-aggregated rows for weekly/monthly
  // ranges; for daily ranges it stays empty and the chart uses dailyPoints.
  const [aggregatedPoints, setAggregatedPoints] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeRangeKey, setActiveRangeKey] = useState<string>(DEFAULT_RANGE_KEY);

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

  // Re-fetch chart data when the active range needs server-side aggregation.
  // For daily ranges we already have everything in dailyPoints and skip the
  // round-trip; for weekly/monthly we ask the backend to GROUP BY + AVG so the
  // payload stays small even on the year/all views.
  useEffect(() => {
    if (!selected) return;
    if (activeRange.granularity === "daily") {
      setAggregatedPoints([]);
      return;
    }
    const from = rangeFromIso(dailyPoints, activeRange);
    const opts: Parameters<typeof productHistory>[1] = {
      granularity: activeRange.granularity,
    };
    if (from) opts.from = from;
    productHistory(selected, opts)
      .then(setAggregatedPoints)
      .catch((e) => setError(String(e)));
  }, [selected, activeRange, dailyPoints]);

  const buckets = useMemo(() => computeBuckets(dailyPoints), [dailyPoints]);
  const chartPoints = useMemo(() => {
    if (activeRange.granularity === "daily") {
      return buildChartSeries(dailyPoints, activeRange);
    }
    // Aggregated rows are already at the target granularity; only the
    // gap-fill interpolation still has to run.
    return buildChartSeries(aggregatedPoints, activeRange);
  }, [dailyPoints, aggregatedPoints, activeRange]);
  const summary = products.find((p) => p.product_name === selected);

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
                {granularityLabel(activeRange.granularity)} · eksik noktalar regresyonla
                doldurulmuştur
              </span>
            </h2>
            <PriceChart points={chartPoints} cityNames={cityNames} />
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
 * Compute the inclusive ``from`` date for the active range, anchored on the
 * latest bulletin date we have in ``daily`` (so the window matches the actual
 * data, not the wall clock). Returns ``undefined`` for ``"today"`` and
 * ``"all"`` so the backend either keys off its own latest date or omits the
 * filter entirely.
 */
function rangeFromIso(daily: HistoryPoint[], range: RangeDef): string | undefined {
  if (range.days === "all" || range.days === "today") return undefined;
  if (daily.length === 0) return undefined;
  const sorted = [...daily].sort((a, b) => a.bulletin_date.localeCompare(b.bulletin_date));
  const latestIso = sorted[sorted.length - 1].bulletin_date;
  const from = new Date(latestIso + "T00:00:00Z");
  from.setUTCDate(from.getUTCDate() - range.days);
  return from.toISOString().slice(0, 10);
}

/**
 * Build the actual chart-input series for the active range. Steps:
 * 1. Filter raw points to the window implied by ``range.days`` (anchored on the
 *    latest available bulletin_date).
 * 2. Bucket every point into either a calendar day or the Monday of its ISO
 *    week, depending on ``range.granularity``.
 * 3. Average prices within each (series, bucket) pair so each (city × category
 *    × variety) line gets one value per bucket.
 * 4. Linearly interpolate buckets that fall *inside* the series's known range
 *    but have no observation. No extrapolation past the first / last known
 *    bucket — those gaps stay empty rather than fabricate trends.
 *
 * The output is in the same ``HistoryPoint`` shape the chart already expects,
 * so we don't need to touch the chart component.
 */
export function buildChartSeries(points: HistoryPoint[], range: RangeDef): HistoryPoint[] {
  if (points.length === 0) return [];

  const sorted = [...points].sort((a, b) => a.bulletin_date.localeCompare(b.bulletin_date));
  const latestIso = sorted[sorted.length - 1].bulletin_date;

  const inWindow = (() => {
    if (range.days === "all") return sorted;
    if (range.days === "today") return sorted.filter((p) => p.bulletin_date === latestIso);
    const from = new Date(latestIso + "T00:00:00Z");
    from.setUTCDate(from.getUTCDate() - range.days);
    const fromIso = from.toISOString().slice(0, 10);
    return sorted.filter((p) => p.bulletin_date >= fromIso);
  })();

  if (inWindow.length === 0) return [];

  // Window endpoints for bucket-sequence generation.
  const windowFromIso = inWindow[0].bulletin_date;
  const windowToIso = inWindow[inWindow.length - 1].bulletin_date;

  // Group by series (city × category × variety).
  const bySeries = new Map<string, HistoryPoint[]>();
  for (const p of inWindow) {
    const key = seriesKey(p);
    const arr = bySeries.get(key) ?? [];
    arr.push(p);
    bySeries.set(key, arr);
  }

  const out: HistoryPoint[] = [];
  for (const seriesPoints of bySeries.values()) {
    const template = seriesPoints[0];

    // Aggregate to bucket → mean(average_price). Bucket key is the start
    // of the bucket (day, Monday of week, or first of month).
    const byBucket = new Map<string, number[]>();
    for (const p of seriesPoints) {
      const bucket = bucketKey(p.bulletin_date, range.granularity);
      const n = Number(p.average_price);
      if (!Number.isFinite(n)) continue;
      const arr = byBucket.get(bucket) ?? [];
      arr.push(n);
      byBucket.set(bucket, arr);
    }
    if (byBucket.size === 0) continue;

    const known = Array.from(byBucket.entries())
      .map(([bucket, vals]) => ({ bucket, value: vals.reduce((s, n) => s + n, 0) / vals.length }))
      .sort((a, b) => a.bucket.localeCompare(b.bucket));

    const allBuckets = bucketSequence(windowFromIso, windowToIso, range.granularity);
    const filled = linearFill(allBuckets, known);

    for (const { bucket, value } of filled) {
      out.push({
        ...template,
        bulletin_date: bucket,
        average_price: String(value),
      });
    }
  }

  return out;
}

function seriesKey(p: HistoryPoint): string {
  return [p.city_slug, p.product_category ?? "", p.product_variety ?? ""].join("|");
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

/**
 * Compute the bucket-start ISO date for ``iso`` at the given granularity.
 *
 * - ``"daily"``  → the date itself.
 * - ``"weekly"`` → the Monday of the ISO week containing the date.
 * - ``"monthly"``→ the first day of the calendar month containing the date.
 */
export function bucketKey(iso: string, granularity: Granularity): string {
  switch (granularity) {
    case "daily":
      return iso;
    case "weekly":
      return isoWeekStart(iso);
    case "monthly":
      return monthStart(iso);
  }
}

/**
 * Return ``YYYY-MM-DD`` of the Monday of the ISO week that contains ``iso``.
 * ISO weeks start on Monday; Sunday belongs to the previous week.
 */
export function isoWeekStart(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  const weekday = d.getUTCDay(); // 0=Sunday, 1=Monday, … 6=Saturday
  const offsetToMonday = weekday === 0 ? -6 : 1 - weekday;
  d.setUTCDate(d.getUTCDate() + offsetToMonday);
  return d.toISOString().slice(0, 10);
}

/**
 * Return ``YYYY-MM-01`` of the calendar month that contains ``iso``.
 */
export function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

/**
 * Inclusive list of bucket-start ISO dates between ``fromIso`` and ``toIso``
 * at the given granularity. Boundaries snap to the start of the bucket the
 * input falls into.
 */
export function bucketSequence(fromIso: string, toIso: string, granularity: Granularity): string[] {
  const out: string[] = [];
  if (granularity === "daily") {
    const d = new Date(fromIso + "T00:00:00Z");
    const end = new Date(toIso + "T00:00:00Z");
    while (d <= end) {
      out.push(d.toISOString().slice(0, 10));
      d.setUTCDate(d.getUTCDate() + 1);
    }
    return out;
  }
  if (granularity === "weekly") {
    const startMon = new Date(isoWeekStart(fromIso) + "T00:00:00Z");
    const endMon = new Date(isoWeekStart(toIso) + "T00:00:00Z");
    while (startMon <= endMon) {
      out.push(startMon.toISOString().slice(0, 10));
      startMon.setUTCDate(startMon.getUTCDate() + 7);
    }
    return out;
  }
  // monthly
  const start = new Date(monthStart(fromIso) + "T00:00:00Z");
  const end = new Date(monthStart(toIso) + "T00:00:00Z");
  while (start <= end) {
    out.push(start.toISOString().slice(0, 10));
    start.setUTCMonth(start.getUTCMonth() + 1);
  }
  return out;
}

/**
 * Linearly interpolate values for every bucket in ``allBuckets`` that has no
 * observation in ``known``. ``known`` must be sorted ascending by ``bucket``.
 *
 * Buckets earlier than the first known one or later than the last are dropped
 * — we never extrapolate past the data we have.
 */
export function linearFill(
  allBuckets: string[],
  known: { bucket: string; value: number }[],
): { bucket: string; value: number }[] {
  if (known.length === 0) return [];
  const knownMap = new Map(known.map((k) => [k.bucket, k.value]));
  const first = known[0].bucket;
  const last = known[known.length - 1].bucket;

  const out: { bucket: string; value: number }[] = [];
  let nextKnownIdx = 0;
  for (const bucket of allBuckets) {
    if (bucket < first || bucket > last) continue;
    const direct = knownMap.get(bucket);
    if (direct !== undefined) {
      out.push({ bucket, value: direct });
      // Advance nextKnownIdx past this bucket so the search below stays O(n).
      while (nextKnownIdx < known.length && known[nextKnownIdx].bucket <= bucket) nextKnownIdx++;
      continue;
    }
    // Find the bracketing known points.
    let leftIdx = nextKnownIdx - 1;
    while (leftIdx >= 0 && known[leftIdx].bucket >= bucket) leftIdx--;
    const left = leftIdx >= 0 ? known[leftIdx] : null;
    let rightIdx = nextKnownIdx;
    while (rightIdx < known.length && known[rightIdx].bucket <= bucket) rightIdx++;
    const right = rightIdx < known.length ? known[rightIdx] : null;
    if (!left || !right) continue; // boundary — leave gap rather than extrapolate
    const t =
      (msFromIso(bucket) - msFromIso(left.bucket)) /
      (msFromIso(right.bucket) - msFromIso(left.bucket));
    out.push({ bucket, value: left.value + (right.value - left.value) * t });
  }
  return out;
}

function msFromIso(iso: string): number {
  return new Date(iso + "T00:00:00Z").getTime();
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
