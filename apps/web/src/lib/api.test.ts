import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// Pin the API base BEFORE importing the module under test.
process.env.NEXT_PUBLIC_API_URL = "http://api.test";
vi.stubGlobal("process", {
  ...process,
  env: { ...process.env, NEXT_PUBLIC_API_URL: "http://api.test" },
});

const cities = [{ slug: "national", name: "National", source_type: "hal_gov_tr", enabled: true }];
const samplePrices = [
  {
    bulletin_date: "2026-05-11",
    product_name: "Domates",
    product_variety: "Salka",
    product_category: "Geleneksel/Konvansiyonel",
    average_price: "18.4000",
    transaction_volume: 1250,
    unit_name: "Kg",
  },
];
const sampleHistory = [
  {
    bulletin_date: "2026-05-10",
    city_slug: "national",
    product_variety: null,
    product_category: "Geleneksel/Konvansiyonel",
    average_price: "17.50",
    unit_name: "Kg",
  },
];

const server = setupServer(
  http.get("http://api.test/api/cities", () => HttpResponse.json(cities)),
  http.get("http://api.test/api/cities/national/prices", ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get("date") === "2026-05-10") return HttpResponse.json([]);
    return HttpResponse.json(samplePrices);
  }),
  http.get("http://api.test/api/products/Domates/history", () => HttpResponse.json(sampleHistory)),
  http.get(
    "http://api.test/api/cities/unknown/prices",
    () => new HttpResponse("nope", { status: 404 }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("api client", () => {
  it("listCities hits /api/cities", async () => {
    const { listCities } = await import("./api");
    const out = await listCities();
    expect(out).toEqual(cities);
  });

  it("cityPrices appends ?date=... when a date is provided", async () => {
    const { cityPrices } = await import("./api");
    const out = await cityPrices("national", "2026-05-10");
    expect(out).toEqual([]);
  });

  it("cityPrices without a date returns the latest set", async () => {
    const { cityPrices } = await import("./api");
    const out = await cityPrices("national");
    expect(out[0].product_name).toBe("Domates");
  });

  it("productHistory builds query params correctly", async () => {
    const { productHistory } = await import("./api");
    const out = await productHistory("Domates", { city: "national", from: "2026-01-01" });
    expect(out[0].city_slug).toBe("national");
  });

  it("throws a clear error on non-2xx responses", async () => {
    const { cityPrices } = await import("./api");
    await expect(cityPrices("unknown")).rejects.toThrow(/404/);
  });
});
