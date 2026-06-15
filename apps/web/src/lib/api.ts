/**
 * Typed fetch wrapper for the FastAPI backend.
 *
 * Types mirror the Pydantic models in apps/api/src/local_bazaar/api/prices.py.
 * If the API shape changes, regenerate (or update by hand) — there is no codegen yet.
 */

export type City = {
  slug: string;
  name: string;
  source_type: "hal_gov_tr" | "city_site";
  enabled: boolean;
};

export type PriceRow = {
  bulletin_date: string; // ISO YYYY-MM-DD
  product_name: string;
  product_variety: string | null;
  product_category: string | null;
  average_price: string; // Decimal serialized as string
  transaction_volume: number | null;
  unit_name: string;
};

export type HistoryPoint = {
  bulletin_date: string;
  city_slug: string;
  product_variety: string | null;
  product_category: string | null;
  average_price: string;
  unit_name: string;
  /** True when the point was synthesized by the server's regression gap-fill. */
  interpolated: boolean;
};

export type ProductSummary = {
  product_name: string;
  unit_name: string;
  latest_bulletin_date: string;
  latest_average_price: string;
};

export type Province = {
  slug: string;
  name: string;
  plate_code: number | null;
};

export type District = {
  slug: string;
  name: string;
  province_slug: string;
};

export type MarketTypeSlug = "semt_pazari" | "uretici_pazari";

export type MarketOut = {
  id: number;
  name: string;
  market_type: MarketTypeSlug;
  address: string | null;
  day_of_week: string | null;
  latitude: number | null;
  longitude: number | null;
  province: string;
  district: string;
};

// Same-origin by default — the browser hits /api on the web host, and the
// Next.js server proxies to the internal API (see next.config.mjs rewrites).
// Set NEXT_PUBLIC_API_URL only if you need to point the browser at a
// different host (e.g. for a separate domain in production).
const API_BASE = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    // SSR-friendly default — price data is daily, no need to bust per request.
    next: { revalidate: 60 },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export function listCities(): Promise<City[]> {
  return get<City[]>("/api/cities");
}

export function cityPrices(slug: string, date?: string): Promise<PriceRow[]> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return get<PriceRow[]>(`/api/cities/${encodeURIComponent(slug)}/prices${qs}`);
}

export function listProducts(city?: string): Promise<ProductSummary[]> {
  const qs = city ? `?city=${encodeURIComponent(city)}` : "";
  return get<ProductSummary[]>(`/api/products${qs}`);
}

export function listProvinces(): Promise<Province[]> {
  return get<Province[]>("/api/provinces");
}

export function listDistricts(provinceSlug: string): Promise<District[]> {
  return get<District[]>(`/api/provinces/${encodeURIComponent(provinceSlug)}/districts`);
}

export function listMarkets(opts?: {
  province?: string;
  district?: string;
  type?: MarketTypeSlug;
  day?: string;
  geocoded?: boolean;
}): Promise<MarketOut[]> {
  const params = new URLSearchParams();
  if (opts?.province) params.set("province", opts.province);
  if (opts?.district) params.set("district", opts.district);
  if (opts?.type) params.set("type", opts.type);
  if (opts?.day) params.set("day", opts.day);
  if (opts?.geocoded) params.set("geocoded", "true");
  const qs = params.toString();
  return get<MarketOut[]>(`/api/markets${qs ? `?${qs}` : ""}`);
}

export type PageViewIncrement = {
  path: string;
  visit_count: number;
};

export type PageView = {
  path: string;
  visit_count: number;
  first_visited_at: string; // ISO timestamp
  last_visited_at: string;
};

export async function recordPageView(path: string): Promise<PageViewIncrement> {
  const res = await fetch(`${API_BASE}/api/page-views`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/page-views failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as PageViewIncrement;
}

export function listPageViews(): Promise<PageView[]> {
  return get<PageView[]>("/api/page-views");
}

export type HistoryGranularity = "daily" | "weekly" | "monthly";

export function productHistory(
  name: string,
  opts?: {
    city?: string;
    from?: string;
    to?: string;
    /** ``"weekly"`` / ``"monthly"`` ask the backend to pre-aggregate via ``date_trunc + AVG``. */
    granularity?: HistoryGranularity;
    /** Ask the backend to fill gaps per series via least-squares regression. */
    fill?: boolean;
  },
): Promise<HistoryPoint[]> {
  const params = new URLSearchParams();
  if (opts?.city) params.set("city", opts.city);
  if (opts?.from) params.set("from", opts.from);
  if (opts?.to) params.set("to", opts.to);
  if (opts?.granularity && opts.granularity !== "daily") {
    params.set("granularity", opts.granularity);
  }
  if (opts?.fill) params.set("fill", "true");
  const qs = params.toString();
  return get<HistoryPoint[]>(
    `/api/products/${encodeURIComponent(name)}/history${qs ? `?${qs}` : ""}`,
  );
}
