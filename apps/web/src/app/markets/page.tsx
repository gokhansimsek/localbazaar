"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { LocateFixed, MapPinPlus } from "lucide-react";
import { MarketsMap } from "@/components/MarketsMap";
import { SuggestionForm } from "@/components/SuggestionForm";
import { cn } from "@/lib/cn";
import {
  listDistricts,
  listMarkets,
  listProvinces,
  type District,
  type MarketOut,
  type MarketTypeSlug,
  type Province,
  type SuggestionType,
} from "@/lib/api";

const TYPES: { value: MarketTypeSlug | "all"; label: string }[] = [
  { value: "all", label: "Tüm türler" },
  { value: "semt_pazari", label: "Semt" },
  { value: "uretici_pazari", label: "Üretici" },
];

const DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"] as const;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default function MarketsPage({ searchParams }: { searchParams: SearchParams }) {
  // Deep links from the footer and mobile tab bar: ?il=<province slug> and
  // ?gun=<day name | "bugun">. The effects below re-apply them when the query
  // changes while this page stays mounted (e.g. clicking another city link).
  const query = use(searchParams);
  const provinceParam = firstParam(query.il);
  const dayParam = firstParam(query.gun);
  const [provinces, setProvinces] = useState<Province[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [province, setProvince] = useState<string>(provinceParam);
  const [district, setDistrict] = useState<string>("");
  const [marketType, setMarketType] = useState<MarketTypeSlug | "all">("all");
  const [day, setDay] = useState<string>(() => dayFromParam(dayParam));

  useEffect(() => {
    setProvince(provinceParam);
  }, [provinceParam]);

  useEffect(() => {
    setDay(dayFromParam(dayParam));
  }, [dayParam]);
  const [markets, setMarkets] = useState<MarketOut[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [locating, setLocating] = useState<boolean>(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  // Place-suggestion flow.
  const [showSuggest, setShowSuggest] = useState<boolean>(false);
  const [suggestMode, setSuggestMode] = useState<SuggestionType>("add");
  const [draftPin, setDraftPin] = useState<{ lat: number; lng: number } | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<MarketOut | null>(null);

  const hasActiveFilter = Boolean(province || district || day) || marketType !== "all";

  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";

  const useMyLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationError("Tarayıcınız konum servisini desteklemiyor.");
      return;
    }
    if (!apiKey) {
      setLocationError("Google Maps API anahtarı tanımlı değil.");
      return;
    }
    if (provinces.length === 0) {
      setLocationError("İl listesi henüz yüklenmedi, lütfen tekrar deneyin.");
      return;
    }
    setLocating(true);
    setLocationError(null);
    navigator.geolocation.getCurrentPosition(
      async ({ coords }) => {
        try {
          const { province: provinceName, district: districtName } = await reverseGeocode(
            coords.latitude,
            coords.longitude,
          );
          if (!provinceName) {
            setLocationError("Konumunuzdan bir il belirlenemedi.");
            return;
          }
          const provinceMatch = matchByName(provinces, provinceName);
          if (!provinceMatch) {
            setLocationError(`"${provinceName}" listemizdeki illerle eşleşmedi.`);
            return;
          }
          setProvince(provinceMatch.slug);

          if (!districtName) {
            setDistrict("");
            return;
          }
          // Fetch the district list directly so we don't have to wait for
          // the province-change effect to repopulate it.
          try {
            const provinceDistricts = await listDistricts(provinceMatch.slug);
            setDistricts(provinceDistricts);
            const districtMatch = matchByName(provinceDistricts, districtName);
            setDistrict(districtMatch ? districtMatch.slug : "");
          } catch {
            setDistrict("");
          }
        } catch (e) {
          setLocationError(String(e));
        } finally {
          setLocating(false);
        }
      },
      (err) => {
        setLocating(false);
        setLocationError(
          err.code === err.PERMISSION_DENIED
            ? "Konum izni reddedildi."
            : `Konum alınamadı: ${err.message}`,
        );
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 5 * 60_000 },
    );
  }, [apiKey, provinces]);

  useEffect(() => {
    listProvinces()
      .then(setProvinces)
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!province) {
      setDistricts([]);
      setDistrict("");
      return;
    }
    let cancelled = false;
    listDistricts(province)
      .then((d) => {
        if (!cancelled) setDistricts(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [province]);

  useEffect(() => {
    if (!hasActiveFilter) {
      setMarkets([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listMarkets({
      province: province || undefined,
      district: district || undefined,
      type: marketType === "all" ? undefined : marketType,
      day: day || undefined,
      geocoded: true,
    })
      .then((m) => {
        if (!cancelled) setMarkets(m);
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
  }, [province, district, marketType, day, hasActiveFilter]);

  const stats = useMemo(() => {
    const total = markets.length;
    const byType: Record<string, number> = {};
    for (const m of markets) byType[m.market_type] = (byType[m.market_type] ?? 0) + 1;
    return { total, byType };
  }, [markets]);

  /**
   * Resolve the most specific human-readable label of the current filter so
   * the map can geocode it when there are no market pins to fit yet (e.g.
   * while the crawler hasn't reached this province).
   */
  const focusLabel = useMemo(() => {
    const distName = districts.find((d) => d.slug === district)?.name;
    if (distName) {
      const provName = provinces.find((p) => p.slug === province)?.name;
      return provName ? `${distName}, ${provName}` : distName;
    }
    return provinces.find((p) => p.slug === province)?.name;
  }, [province, district, provinces, districts]);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-3xl font-semibold lg:text-5xl">Pazar Yerleri</h1>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={useMyLocation}
            disabled={locating}
            className="inline-flex items-center gap-2 rounded-xl border border-surface-border bg-white px-3 py-2 text-sm font-medium text-ink-soft transition-colors hover:border-ink-faint hover:text-crate-700 disabled:opacity-60"
          >
            <LocateFixed size={14} />
            {locating ? "Konum alınıyor…" : "Konumumu Kullan"}
          </button>
          <button
            type="button"
            onClick={() => {
              setShowSuggest((v) => !v);
              setDraftPin(null);
              setSelectedMarket(null);
            }}
            className="btn-primary"
          >
            <MapPinPlus size={14} />
            Yer öner
          </button>
        </div>
      </header>

      {locationError && <div className="card p-3 text-xs text-danger">{locationError}</div>}

      <section className="grid gap-3 sm:grid-cols-3">
        <FilterSelect label="İl" value={province} onChange={setProvince}>
          <option value="">Tüm iller</option>
          {provinces.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.name}
            </option>
          ))}
        </FilterSelect>
        <FilterSelect label="İlçe" value={district} onChange={setDistrict} disabled={!province}>
          <option value="">Tüm ilçeler</option>
          {districts.map((d) => (
            <option key={d.slug} value={d.slug}>
              {d.name}
            </option>
          ))}
        </FilterSelect>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-ink-muted">Tür</span>
          <div className="inline-flex rounded-xl border border-surface-border bg-white p-1">
            {TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setMarketType(t.value)}
                className={cn(
                  "flex-1 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                  marketType === t.value
                    ? "bg-ink text-surface-subtle"
                    : "text-ink-soft hover:bg-surface-muted",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        <span className="font-medium">Gün:</span>
        <button
          type="button"
          onClick={() => setDay("")}
          className={cn(
            "rounded-full px-3 py-1 font-medium transition-colors",
            day === ""
              ? "bg-ink text-surface-subtle"
              : "border border-surface-border bg-white text-ink-soft hover:border-ink-faint hover:text-crate-700",
          )}
        >
          Tümü
        </button>
        {DAYS.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDay(d)}
            className={cn(
              "rounded-full px-3 py-1 font-medium transition-colors",
              day === d
                ? "bg-ink text-surface-subtle"
                : "border border-surface-border bg-white text-ink-soft hover:border-ink-faint hover:text-crate-700",
            )}
          >
            {d}
          </button>
        ))}
      </section>

      <section className="card flex items-center justify-between px-5 py-3 text-sm">
        <div>
          <span className="font-medium text-ink">{stats.total}</span>
          <span className="text-ink-muted"> pazar haritada</span>
        </div>
        <div className="flex gap-4 text-xs text-ink-muted">
          {Object.entries(stats.byType).map(([k, v]) => (
            <span key={k}>
              <span className="font-medium text-ink">{v}</span>{" "}
              {k === "semt_pazari" ? "semt" : "üretici"}
            </span>
          ))}
        </div>
      </section>

      {error && (
        <div className="card p-4 text-sm text-ink-soft">
          Pazarlar şu anda görüntülenemiyor. Birkaç dakika sonra tekrar deneyin.
        </div>
      )}

      {showSuggest && (
        <SuggestionForm
          provinces={provinces}
          mode={suggestMode}
          onModeChange={(m) => {
            setSuggestMode(m);
            setDraftPin(null);
            setSelectedMarket(null);
          }}
          draftPin={draftPin}
          selectedMarket={selectedMarket}
          onClose={() => setShowSuggest(false)}
        />
      )}

      {loading && <div className="card p-3 text-center text-xs text-ink-muted">Yükleniyor…</div>}
      <MarketsMap
        apiKey={apiKey}
        markets={markets}
        focusLabel={focusLabel}
        onMapClick={showSuggest ? (lat, lng) => setDraftPin({ lat, lng }) : undefined}
        draftPin={showSuggest ? draftPin : null}
        selectable={showSuggest && suggestMode === "update"}
        onSelectMarket={setSelectedMarket}
      />
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  children,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-ink-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="rounded-xl border border-surface-border bg-white px-3 py-2 text-sm text-ink outline-none transition-all focus:border-crate-400 focus:shadow-ring disabled:opacity-50"
      >
        {children}
      </select>
    </label>
  );
}

/**
 * Wait for the Google Maps JS SDK to finish loading.
 *
 * `MarketsMap` mounts `<APIProvider>` (which injects the script) as soon as
 * an API key is configured, but a fast click on "Konumumu Kullan" can race
 * ahead of that load — so poll briefly instead of assuming it's ready.
 */
function waitForGoogleMaps(timeoutMs = 8000): Promise<typeof google> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = (): void => {
      if (typeof google !== "undefined" && google.maps?.Geocoder) {
        resolve(google);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        reject(new Error("Google Maps henüz yüklenmedi."));
        return;
      }
      setTimeout(check, 150);
    };
    check();
  });
}

async function reverseGeocode(
  lat: number,
  lng: number,
): Promise<{ province: string | null; district: string | null }> {
  // Reuse the Maps JS SDK that `MarketsMap`'s `<APIProvider>` already loaded
  // (via the browser key) instead of a second REST call — Google's REST
  // Geocoding endpoint expects an IP-restricted server key, not the
  // HTTP-referrer-restricted browser key this project uses for JS libraries.
  const g = await waitForGoogleMaps();
  const geocoder = new g.maps.Geocoder();
  const { results } = await geocoder.geocode({
    location: { lat, lng },
    language: "tr",
    region: "tr",
  });
  // Walk every result and prefer the first administrative_area_level_1 /
  // _level_2 we see. Google may split the answer across multiple results
  // (street, neighborhood, etc.) so we don't assume both live on the same one.
  let province: string | null = null;
  let district: string | null = null;
  for (const result of results) {
    for (const comp of result.address_components) {
      if (!province && comp.types.includes("administrative_area_level_1")) {
        province = comp.long_name;
      }
      if (!district && comp.types.includes("administrative_area_level_2")) {
        district = comp.long_name;
      }
    }
    if (province && district) break;
  }
  return { province, district };
}

function tcLower(s: string): string {
  return s.toLocaleLowerCase("tr-TR").trim();
}

function matchByName<T extends { name: string }>(items: T[], name: string): T | undefined {
  const target = tcLower(name);
  return items.find((item) => tcLower(item.name) === target);
}

function firstParam(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

/** Map a ?gun= value to a DAYS entry; "bugun" resolves to today in Turkey. */
function dayFromParam(value: string): string {
  if (value === "bugun") {
    const today = new Intl.DateTimeFormat("tr-TR", {
      weekday: "long",
      timeZone: "Europe/Istanbul",
    }).format(new Date());
    return DAYS.find((d) => tcLower(d) === tcLower(today)) ?? "";
  }
  return (DAYS as readonly string[]).includes(value) ? value : "";
}
