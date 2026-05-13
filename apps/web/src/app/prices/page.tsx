"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { CitySelector } from "@/components/CitySelector";
import { DateSelector } from "@/components/DateSelector";
import { PriceTable } from "@/components/PriceTable";
import { cityPrices, listCities, type City, type PriceRow } from "@/lib/api";
import { formatDate, todayIso } from "@/lib/format";

// The synthetic "national" city is the default bulletin and is hidden from the
// city pill picker (the user wants the picker to surface real provinces only).
const DEFAULT_CITY_SLUG = "national";

export default function HomePage() {
  const [cities, setCities] = useState<City[]>([]);
  const [activeCity, setActiveCity] = useState<string>(DEFAULT_CITY_SLUG);
  const [date, setDate] = useState<string>("");
  const [rows, setRows] = useState<PriceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCities()
      .then(setCities)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!activeCity) return;
    setLoading(true);
    setError(null);
    cityPrices(activeCity, date || undefined)
      .then((r) => setRows(r))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [activeCity, date]);

  const selectableCities = useMemo(() => {
    const national = cities.find((c) => c.slug === DEFAULT_CITY_SLUG);
    const others = cities.filter((c) => c.slug !== DEFAULT_CITY_SLUG);
    return national ? [national, ...others] : others;
  }, [cities]);

  const bulletinDate = rows[0]?.bulletin_date;

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <span className="chip">Günlük bülten</span>
        <h1 className="text-3xl font-semibold tracking-tight lg:text-4xl">Hal Fiyatları</h1>
        <p className="max-w-2xl text-ink-soft">
          Türkiye&apos;deki hal fiyatlarını ürün ve şehir bazında günlük olarak izleyin. Bir ürüne
          tıklayarak tarihsel grafiğini açın.
        </p>
        {bulletinDate && (
          <p className="text-sm text-ink-muted">
            Bülten tarihi: <span className="font-medium text-ink">{formatDate(bulletinDate)}</span>
          </p>
        )}
      </header>

      <section className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        {selectableCities.length > 0 ? (
          <CitySelector cities={selectableCities} value={activeCity} onChange={setActiveCity} />
        ) : (
          <span className="text-xs text-ink-faint">
            Şehir bazlı veri henüz eklenmedi — ulusal bülten gösteriliyor.
          </span>
        )}
        <DateSelector value={date} onChange={setDate} max={todayIso()} />
      </section>

      {error && (
        <div className="card p-4 text-sm text-ink-soft">
          Bu şehrin fiyatları şu anda görüntülenemiyor. Birkaç dakika sonra tekrar deneyin.
        </div>
      )}

      {loading ? (
        <div className="card p-12 text-center text-ink-muted">Yükleniyor…</div>
      ) : (
        <PriceTable rows={rows} />
      )}

      <footer className="flex items-center gap-1 text-xs text-ink-faint">
        <span>Detaylı analiz için bir ürüne tıklayın</span>
        <ArrowRight size={12} />
      </footer>
    </div>
  );
}
