"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { ArrowLeft, TrendingDown, TrendingUp } from "lucide-react";
import { CitySelector } from "@/components/CitySelector";
import { PriceChart } from "@/components/PriceChart";
import { RangePresets, rangeToFromDate, type RangeKey } from "@/components/RangePresets";
import { listCities, productHistory, type City, type HistoryPoint } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/cn";

type Params = { name: string };

const DEFAULT_CITY_SLUG = "national";

export default function ProductPage({ params }: { params: Promise<Params> }) {
  const { name: rawName } = use(params);
  const name = decodeURIComponent(rawName);

  const [cities, setCities] = useState<City[]>([]);
  const [activeCity, setActiveCity] = useState<string>(DEFAULT_CITY_SLUG);
  const [range, setRange] = useState<RangeKey>("3M");
  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCities()
      .then(setCities)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    productHistory(name, {
      city: activeCity,
      from: rangeToFromDate(range),
    })
      .then((p) => {
        if (!cancelled) setPoints(p);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [name, activeCity, range]);

  const selectableCities = useMemo(
    () => cities.filter((c) => c.slug !== DEFAULT_CITY_SLUG),
    [cities],
  );

  const cityNames = useMemo(
    () => Object.fromEntries(cities.map((c) => [c.slug, c.name])),
    [cities],
  );

  const stats = useMemo(() => computeStats(points), [points]);

  return (
    <div className="space-y-8">
      <Link
        href="/prices"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted transition-colors hover:text-crate-700"
      >
        <ArrowLeft size={14} />
        Bültene dön
      </Link>

      <header className="space-y-2">
        <h1 className="text-3xl font-semibold lg:text-5xl">{name}</h1>
        <p className="text-ink-soft">Seçili şehir için tarihsel ortalama fiyat (₺).</p>
      </header>

      {stats && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Stat label="Son fiyat" value={formatPrice(stats.latest)} tag />
          <Stat label="Önceki periyot" value={formatPrice(stats.first)} delta={stats.deltaPct} />
          <Stat label="Ortalama" value={formatPrice(stats.avg)} />
        </section>
      )}

      <section className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        {selectableCities.length > 0 ? (
          <CitySelector cities={selectableCities} value={activeCity} onChange={setActiveCity} />
        ) : (
          <span className="text-xs text-ink-faint">
            Şehir bazlı veri henüz eklenmedi — ulusal seri gösteriliyor.
          </span>
        )}
        <RangePresets value={range} onChange={setRange} />
      </section>

      {error && (
        <div className="card p-4 text-sm text-ink-soft">
          Bu ürünün geçmişi şu anda yüklenemiyor. Birkaç dakika sonra tekrar deneyin.
        </div>
      )}

      {loading ? (
        <div className="card p-12 text-center text-ink-muted">Yükleniyor…</div>
      ) : (
        <PriceChart points={points} cityNames={cityNames} />
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  delta,
  tag = false,
}: {
  label: string;
  value: string;
  delta?: number;
  tag?: boolean;
}) {
  return (
    <div className="card p-5">
      <div className="text-xs font-medium text-ink-muted">{label}</div>
      <div className="mt-2">
        {tag ? (
          <span className="price-tag text-2xl">{value}</span>
        ) : (
          <span className="font-display text-2xl font-semibold tabular-nums">{value}</span>
        )}
      </div>
      {delta !== undefined && Number.isFinite(delta) && (
        <div
          className={cn(
            "mt-1 inline-flex items-center gap-1 text-xs font-medium",
            delta >= 0 ? "stat-up" : "stat-down",
          )}
        >
          {delta >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {`${delta >= 0 ? "+" : ""}${delta.toFixed(2)} %`}
        </div>
      )}
    </div>
  );
}

function computeStats(points: HistoryPoint[]) {
  if (points.length === 0) return null;
  // Average all variants (variety × category) per day so a single product with
  // multiple production methods does not produce a misleading "latest".
  const byDate = new Map<string, number[]>();
  for (const p of points) {
    const n = Number(p.average_price);
    if (!Number.isFinite(n)) continue;
    const arr = byDate.get(p.bulletin_date) ?? [];
    arr.push(n);
    byDate.set(p.bulletin_date, arr);
  }
  const daily = Array.from(byDate.entries())
    .map(([d, arr]) => ({ d, avg: arr.reduce((s, n) => s + n, 0) / arr.length }))
    .sort((a, b) => a.d.localeCompare(b.d));
  if (daily.length === 0) return null;
  const first = daily[0].avg;
  const latest = daily[daily.length - 1].avg;
  const avg = daily.reduce((s, p) => s + p.avg, 0) / daily.length;
  const deltaPct = first === 0 ? 0 : ((latest - first) / first) * 100;
  return { first, latest, avg, deltaPct };
}
