# CLAUDE.md — Semt Pazarı

Guidance for Claude Code sessions working in this repo.

## Project overview

**Semt Pazarı** is a Turkish neighborhood-markets platform. It ships two features today, with room for more:

1. **Hal Fiyatları** — daily and historical wholesale-market ("hal") prices for agricultural produce, sourced from the national `hal.gov.tr` bulletin plus nine per-city sources. Every price row references a row in a normalized `products` registry (one row per name × variety × category × unit); only fruit/vegetable produce is kept (fish/seafood is dropped).
2. **Pazar Yerleri** — every neighborhood (semt) and producer (üretici) market published by hal.gov.tr, normalized into provinces → districts → markets and geocoded via the Google Maps Geocoding API for display on a map. Visitors can submit crowdsourced add/update suggestions (queued for manual review).

A FastAPI backend exposes the data; a Next.js UI renders a Linear-style landing page at `/`, Hal Fiyatları at `/prices`, historical trends at `/trends`, per-product detail at `/products/[name]`, a Google Maps view of pazar yerleri at `/markets`, and a privacy policy at `/privacy`. The system is deployed as containers on AWS via Kubernetes.

### Internal naming

Internal identifiers use `local_bazaar` (snake) / `local-bazaar` (kebab) consistently across code, infra, and storage. **User-visible strings — page titles, top header, OpenAPI summary, README — say "Semt Pazarı".**

- `apps/api/src/local_bazaar/` — Python package and all imports
- `apps/api/pyproject.toml` — ``name = "local_bazaar"``
- `deploy/k8s/.../*` — namespace `local-bazaar`, label `app.kubernetes.io/part-of: local-bazaar`
- The Postgres role / DB name is whatever the external Postgres (RDS) is provisioned with; the example URLs in `.env.example` use `local_bazaar` but the application only cares about `DATABASE_URL`.

## Status

Scaffolding is complete and gated by quality tools. The repo has:

- A working monorepo (`apps/api`, `apps/web`, `deploy/k8s`).
- Fourteen Alembic migrations:
  - `0001_initial_schema` (cities + scrape_runs + `prices_national` + provinces + districts + markets)
  - `0002_seed_tr_geography` (81 provinces + 973 districts from a checked-in JSON fixture)
  - `0003_widen_markets_address` (column widen for free-text addresses)
  - `0004_seed_city_scrapers` (registers 9 per-city scrapers: adana, ankara, antalya, bursa, istanbul, izmir, kocaeli, konya, sanliurfa)
  - `0005_page_views` (atomic per-path visit counters)
  - `0006_products` (normalized `products` registry, seeded from distinct `prices_national` tuples)
  - `0007_prices_product_id` (adds + backfills `product_id` FK on every `prices_<slug>` table)
  - `0008_drop_non_produce` (deletes fish/seafood rows + orphaned products; keeps İthal produce)
  - `0009_drop_legacy_price_columns` (switches `prices_*` uniqueness to `(bulletin_date, product_id)`, drops the legacy text columns, makes `product_id` NOT NULL)
  - `0010_normalize_units_cleanup` (canonicalizes `products.unit_name`, drops mis-parsed rows)
  - `0011_normalize_categories` (rewrites categories to the four canonical grades)
  - `0012_promote_category_words` (moves İthal/Yerli tags from `variety` into `category`)
  - `0013_merge_turp_otu` (merges split `(Turp, Otu)` rows into `(Turp Otu, NULL)`)
  - `0014_user_place_suggestions` (lightweight `users` + `place_suggestions` tables for the suggestion feature)
- Eleven scrapers:
  - `hal_gov_tr` — national bulletin (synthetic city `national`)
  - `bazaar_locations` — every neighborhood + producer market across all 81 provinces
  - `cities/{adana,ankara,bursa,istanbul,izmir,kocaeli,konya,sanliurfa}` — plain HTTP scrapers
  - `cities/antalya` — Playwright-driven scraper (the source is a Vue SPA)
- A Linear-style homepage at `/` with three embedded animated UI previews (Markets, Prices, Trends). Sticky top header replaces the old left sidebar; the homepage cards act as primary navigation.
- Google Maps geocoding (`geocoding.py`) and a map page (`/markets`) with a "Konumumu Kullan" button that reverse-geocodes the browser's coordinates into both province (`administrative_area_level_1`) and district (`administrative_area_level_2`), plus an in-page **suggestion form** for proposing new markets (drop a pin) or corrections to existing ones.
- A **hidden, token-gated admin page** at `/admin/suggestions` (no nav link, `noindex` — reached by typing the URL) to review pending suggestions and **approve** (auto-applies: an `add` creates/reuses the `markets` row, resolving the pin's district via reverse geocoding; an `update` applies corrected coordinates) or **reject** them. Access is gated by a shared `ADMIN_TOKEN` sent in the `X-Admin-Token` header.
- A `/trends` page with a searchable product picker, a Hal (city) multiselect filter, daily/weekly/monthly granularity, and optional server-side least-squares gap-fill on the chart.
- Page-view analytics: a fire-and-forget `POST /api/page-views` from the client (`PageViewCounter`) increments per-path counters on an allow-list of routes.
- Per-IP rate limiting on every `/api/*` route via **slowapi** (`API_RATE_LIMIT`, default `120/minute`), returning a clean JSON 429.
- Google AdSense + Funding Choices CMP integration, all inert unless `NEXT_PUBLIC_ADSENSE_CLIENT_ID` is set; `/privacy` and `/ads.txt` routes back it.
- Network-private API model: the browser only ever talks to same-origin `/api/*` on the web service; Next.js proxies via the server-side `API_INTERNAL_URL` rewrite. Locally the API port binds to `127.0.0.1:8000`; in Kubernetes the API Service is `ClusterIP` and the Ingress only routes `/`. `/docs`, `/redoc`, `/openapi.json` are gated by `ENABLE_API_DOCS` (off by default; the local docker-compose sets it to 1 for dev).
- Pre-commit hooks enforcing ruff + flake8 + pyright (Python) and prettier + eslint + tsc (TypeScript). All three Python linters currently report zero issues on `apps/api/src`.

Git is initialized. When code drifts from this document, trust the code and update this file.

## Domain & data sources

### Primary source — hal.gov.tr

- URL: `https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx`
- ASP.NET WebForms — pagination uses `__doPostBack` against `__VIEWSTATE`/`__EVENTVALIDATION`. The GridView id contains `gvFiyatlar`.
- **No city dropdown on this page** — it is national/aggregate data. We store its rows under the synthetic city slug `national` (seeded by the initial migration; display name `National`).
- The scraped product descriptors are normalized into the shared `products` registry; each `prices_<slug>` row keeps only `product_id` (FK) + the numeric/audit columns. Descriptor fields live on `products`:

| Turkish header   | DB column (`products`) | Type / notes      |
|------------------|------------------------|-------------------|
| Ürün Adı         | `name`                 | TEXT              |
| Ürün Cinsi       | `variety`              | TEXT (nullable)   |
| Ürün Türü        | `category`             | TEXT — canonicalized to one of `Geleneksel(Konvansiyonel)`, `İyi Tarım`, `Organik Tarım`, `İthal` |
| Birim Adı        | `unit_name`            | TEXT — canonicalized (`Kg`, `Adet`, `Bağ`, `Demet`, `Paket`, …) |

  Numeric/audit columns live on each `prices_<slug>` row: `bulletin_date` (DATE, Turkey time), `product_id` (BIGINT FK → `products.id`), `average_price` (NUMERIC(12,4) TRY), `transaction_volume` (BIGINT, nullable), `last_updated` (TIMESTAMPTZ). The price-list and history endpoints re-join `products`, so the API still returns flat `product_name` / `product_variety` / `product_category` / `unit_name` fields to the frontend.

### Secondary source — per-city hal prices

Nine cities have dedicated scrapers under `apps/api/src/local_bazaar/scrapers/cities/`. Each one exposes `async run(session) -> int` and is auto-discovered by the scheduler from the `cities` table (rows with `source_type='city_site'`). All emit `ProductPrice(city_name=...)` records and persist via `upsert_prices`, which routes to the right `prices_<slug>` table. Default lookback is 160 days; days already in the per-city table are skipped, so repeat runs are cheap.

| slug | source | mechanism | notes |
|------|--------|-----------|-------|
| `istanbul` | `tarim.ibb.istanbul/.../hal-fiyatlari.html` | AJAX `gunluk_fiyatlar.asp?tarih=YYYY-MM-DD&kategori=N` × 3 categories | midpoint of En Düşük/En Yüksek |
| `ankara` | `ankara.bel.tr/hal-fiyatlari` | Laravel POST with CSRF token, 4 product types per date | per-row Tarih is authoritative |
| `bursa` | `bursa.bel.tr/hal_fiyatlari` | GET `?sayfa=hal_fiyatlari&tarih=YYYY-MM-DD` (ISO format only — dd.mm.yyyy returns empty) | 9 product tabs |
| `konya` | `konya.bel.tr/hal-fiyatlari` | GET `?tarih=YYYY-MM-DD` | Sebze + Meyve tables, ~80 dates/year |
| `kocaeli` | `kocaeli.bel.tr/hal-fiyatlari/d-YYYY-MM-DD-h-1.html` | date encoded in path; single hall (h-1) | category Sebze/Meyve in-row |
| `izmir` | `eislem.izmir.bel.tr/tr/HalFiyatlari/` | GET `?date=YYYY-MM-DD&tip=N` × 3 categories | source publishes `Ortalama` directly |
| `sanliurfa` | `halfiyatlari.sanliurfa.bel.tr` | GET `?search=1&start_date=...&end_date=...&product_type_id=N` | uses DOT decimal separator, not comma |
| `adana` | `adana.bel.tr/tr/hal-fiyat-listesi` | listing-page → detail-page (`/tr/hal-detay/<id>`); date in `<h4>` header | two-layer scraper |
| `antalya` | `antalya.bel.tr/tr/halden-gunluk-fiyatlar` | **Playwright** — Vue 3 SPA with obfuscated AJAX endpoint | drives headless Chromium |

Prices are min/max ranges on most sources; we store the midpoint as `average_price`. Where the source publishes a real average (Izmir's `Ortalama` column) we use it directly. Adding a new city: write `scrapers/cities/<slug>.py` following the same pattern, then add a row to the `cities` table in a new migration.

### Tertiary source — pazar yerleri (markets)

- URL: `https://www.hal.gov.tr/Sayfalar/Pazar-Yerleri.aspx`
- ASP.NET WebForms search: select il (`ddlIl`), ilçe (`ddlIlce`), and market type (`ddlTur`), then submit `BtnAra`. Submitting fires postbacks with the GUID-prefixed control names `ctl00$ctl37$g_<guid>$<leaf>`.
- The crawler iterates every province × district × market-type combination, parses the result block, and UPSERTs into `markets` referencing `districts` and `provinces` by FK.
- Two market types are recognized: `Semt Pazarı` (neighborhood) and `Üretici Pazarı` (producer).
- The scraper itself never calls Google. After scraping, geocoding is opt-in via `scripts/geocode_markets.py` (which delegates to `local_bazaar.geocoding`) to fill in `latitude` / `longitude` for any markets with NULL coordinates. The same API key powers the frontend map widget (`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`).

### Update cadence

- Daily scrape at 02:00 Europe/Istanbul.
- Locally / in `docker compose`, the in-process apscheduler runs `run_daily_scrape()` — national bulletin + **all** per-city scrapers + the markets crawl (geocoding excluded).
- In-cluster, the in-process scheduler is disabled (`SCRAPER_DISABLE_SCHEDULER=1`) and the CronJob `scrape-daily` is the canonical trigger. It runs `python -m local_bazaar.scheduler`, whose `_main()` calls `run_daily_scrape()` once and exits — so it covers the same work as the in-process scheduler (national bulletin + all per-city scrapers + markets crawl; geocoding excluded). The Job allows 2 h and 1Gi (the markets crawl + Antalya's headless Chromium need the headroom).
- See **Running the scrapers** in `README.md` for the full local + cloud runbook.

## Database schema

PostgreSQL 17. The schema has four concerns: the shared `products` registry, per-city price tables, normalized geography (provinces → districts → markets), and audit / registry / engagement tables.

### Products registry

- `products (id, name, variety, category, unit_name, created_at)` — one row per distinct produce descriptor.
- Unique index `uq_products_full` on `(name, COALESCE(variety, ''), COALESCE(category, ''), unit_name)` (the COALESCE keeps NULL variety/category from counting as distinct).
- `category` is one of the four canonical grades (`Geleneksel(Konvansiyonel)`, `İyi Tarım`, `Organik Tarım`, `İthal`); `unit_name` is canonicalized. Fish/seafood and mis-parsed rows have been pruned (migrations 0008/0010).

### Per-city prices

- `prices_<city_slug>` (e.g. `prices_national`, `prices_istanbul`).
- Columns: `id`, `bulletin_date`, `product_id` (BIGINT FK → `products.id`, NOT NULL), `average_price`, `transaction_volume`, `last_updated`. Legacy text descriptor columns were dropped in migration 0009.
- Unique constraint `(bulletin_date, product_id)` to make UPSERTs idempotent.
- Registry: `cities (id, slug, name, source_type, source_url, enabled, created_at)`.
- Cross-city queries use UNION ALL over registered tables. There is **also** a SQL-generated UNION pattern in `api/prices.py::product_history` and a helper `db.rebuild_prices_view()` that can (re)create a `prices_all` view if you prefer querying through it.

### Geography + markets

- `provinces (id, slug, name, plate_code, created_at)` — one row per Turkish il.
- `districts (id, province_id FK, slug, name, created_at)` — one row per ilçe, PK/FK to provinces.
- `markets (id, district_id FK, market_type, name, address, day_of_week, latitude, longitude, geocoded_at, last_seen, created_at)` — one row per physical market.
- Unique on `(district_id, market_type, name)` for idempotent UPSERTs (the scraper folds parenthetical sub-sections like `"... (BALIK BÖLÜMÜ)"` into the same logical market).
- `latitude`/`longitude` are populated by `scripts/geocode_markets.py` (which calls `local_bazaar.geocoding`), not by the scraper itself or by the daily scheduler.

### Suggestions (crowdsourced markets)

- `users (id, first_name, last_name, email UNIQUE, province_id FK, district_id FK, created_at)` — lightweight, password-less submitters deduped by email (the unique index is the `ON CONFLICT` target for the upsert).
- `place_suggestions (id, user_id FK, suggestion_type, status, market_id FK, proposed_name, proposed_market_type, province_id FK, district_id FK, latitude, longitude, explanation, created_at, reviewed_at, review_note)` — one `add` or `update` request per row. `add` rows carry the proposed name/type + pinned coordinates; `update` rows reference an existing `markets` row. Rows are stored `status='pending'`; nothing is auto-applied on submission. An operator reviews them via the hidden, token-gated `/admin/suggestions` page (which auto-applies on approve) or directly in the DB.

### Audit & engagement

- `scrape_runs (scraper, city_slug, bulletin_date, status, rows_written, error, started_at, finished_at)` — UI staleness banners can read from this.
- `page_views (id, path UNIQUE, visit_count, first_visited_at, last_visited_at)` — atomic per-path counters, incremented via `POST /api/page-views` on an allow-list of routes.

The slug helper is `db.city_slug()` — Turkish-aware ASCII folding (`İstanbul → istanbul`, `Şanlıurfa → sanliurfa`). Do not re-implement.

## Architecture

```
[Browser] ──HTTP──> [Next.js web]  ──/api proxy──>  [FastAPI API]  ──SQL──> [PostgreSQL]
                                                       │
                                Local dev only ────────┴── apscheduler ──> [Scrapers]

                                In cluster: CronJob `scrape-daily` ─────> [Scrapers]
```

- Scrapers live inside the API package and are reused by both the in-process scheduler (dev) and the CronJob (prod).
- **The API is never reached directly by the browser.** The web service proxies same-origin `/api/*` calls to `API_INTERNAL_URL` via a Next.js `rewrites()` rule (`apps/web/next.config.mjs`). Locally the API port binds to `127.0.0.1:8000`; in Kubernetes the API Service is `ClusterIP` only and the Ingress has no `/api` rule. The internal cluster URL is `http://api:8000` (Service port matches the container port; this avoids per-environment routes-manifest rebuilds since Next.js bakes the upstream URL at build time).
- **`/docs`, `/redoc`, `/openapi.json` are gated** by `ENABLE_API_DOCS`. Off by default; docker-compose sets it to `1` for dev, K8s leaves it unset so prod returns 404.
- **Per-IP rate limiting** via `slowapi` (`SlowAPIMiddleware`) applies `API_RATE_LIMIT` (default `120/minute`) to every `/api/*` route; a custom handler returns a JSON 429 with `Retry-After`. `structlog` provides structured logging.

### API surface (`/api` prefix, read-only except the suggestion/page-view POSTs and the token-gated admin endpoints)

All endpoints are mounted under `/api`; `GET /healthz` (no prefix) is the K8s liveness probe.

- **prices** — `GET /cities`, `GET /cities/{slug}/prices?date=`, `GET /products?city=`, `GET /products/{name}/history?from=&to=&city=&granularity=daily|weekly|monthly&fill=`. History supports per-series least-squares gap-fill (`fill=true` marks synthesized points `interpolated`); all-zero series are dropped.
- **markets** — `GET /provinces`, `GET /provinces/{slug}/districts`, `GET /markets?province=&district=&type=&day=&geocoded=`.
- **page-views** — `POST /page-views` (atomic increment, allow-list of paths), `GET /page-views` (leaderboard).
- **suggestions** — `POST /suggestions` (upserts the user by email, stores a `pending` add/update suggestion; honeypot `website` field for spam).
- **admin** (token-gated — `X-Admin-Token` must equal `ADMIN_TOKEN`; 503 when unset, 401 on mismatch) — `GET /admin/suggestions?status=`, `POST /admin/suggestions/{id}/approve` (auto-applies), `POST /admin/suggestions/{id}/reject`.

Frontend types mirror these in `apps/web/src/lib/api.ts`; keep both in sync.

## Tech stack (established)

### Backend — `apps/api`

- **Python 3.14** (latest stable, May 2026). `requires-python = ">=3.14"`.
- FastAPI + `uvicorn[standard]`, `pydantic-settings`
- SQLModel + SQLAlchemy 2.x async, `psycopg[binary]` driver
- Alembic for migrations (registry tables tracked; per-city `prices_*` tables created via raw DDL helpers in `db.ensure_city_table()`)
- `slowapi` for per-IP rate limiting; `structlog` for structured logging
- `httpx` + `selectolax` for scraping; `tenacity` for retries; `python-dateutil` for date math; `playwright` is installed in the production image (for the Antalya scraper, which targets a Vue SPA). Chromium is installed at `/opt/playwright-browsers` via `playwright install --with-deps chromium` in the runtime stage.
- `apscheduler` (in-process daily job; disabled in cluster — replaced by the `scrape-daily` CronJob)
- Quality (under `[project.optional-dependencies].dev`):
  - **ruff** (lint + format) with rule families `E F I B UP SIM ASYNC RUF D ANN`, Google docstring convention
  - **flake8** with `flake8-bugbear`, `flake8-comprehensions`, `flake8-docstrings`
  - **pyright** in `standard` mode (config at `apps/api/pyrightconfig.json`)
  - **pytest** + `pytest-asyncio` + `pytest-cov` + `respx`
- Package manager: **uv**

### Frontend — `apps/web`

- **Next.js 16.2** (App Router) + **React 19.1** + TypeScript (strict)
- Package manager: **pnpm 9.15.0** (via Corepack), Node >= 20.18
- Styling: **TailwindCSS** + a Stripe-inspired token set defined in `tailwind.config.ts` (brand indigo `#635BFF`, off-white `#F6F9FC`, deep navy ink `#0A2540`, gradients toward sky `#00D4FF` / pink `#FF7AB6`)
- Charts: `recharts`
- Maps: `@vis.gl/react-google-maps` (Google Maps JS API wrapper)
- Icons: `lucide-react`
- Date picker: `react-day-picker` (Turkish locale); date math via `date-fns`
- Monetization: Google AdSense + Funding Choices CMP, gated entirely behind `NEXT_PUBLIC_ADSENSE_*` env (inert when unset)
- Date / number formatting via Intl in `src/lib/format.ts`
- API client is hand-typed in `src/lib/api.ts` (no codegen yet — keep types in sync with the Pydantic models in `apps/api/src/local_bazaar/api/`)
- Quality: **eslint** (Next.js 16 native flat config in `eslint.config.mjs`), **prettier** (with `prettier-plugin-tailwindcss`), **tsc --noEmit**, **vitest** + `@testing-library/react` + `msw`

### Infra

- Docker: multi-stage per service. API uses `python:3.14-slim` + `uv`; Web uses `node:20-alpine` + `pnpm` + Next.js standalone output.
- Kubernetes: Kustomize under `deploy/k8s/{base,overlays/{dev,prod,local}}` — Deployments (api, web), Services, ALB Ingress, ConfigMaps, CronJob, plus a `secrets.example.yaml` for shape (do **not** commit real Secrets). The `local` overlay targets Docker Desktop k8s (no ingress controller required; web exposed via `LoadBalancer` on `localhost:8080`; `imagePullPolicy: Never` so images come from the local containerd `k8s.io` namespace — Docker Desktop's k8s does NOT share its image store with the Docker daemon, so each rebuild needs `docker save | docker exec desktop-control-plane ctr -n k8s.io images import -`).
- AWS targets: **EKS**, **RDS PostgreSQL**, **ECR**, **ALB** via AWS Load Balancer Controller, **Secrets Manager** + External Secrets Operator.
- Terraform skeleton for EKS / RDS / ECR / VPC / IAM is planned at `deploy/terraform/` (not yet scaffolded — add when infra work begins).

## Directory layout (established)

```
local_bazaar/
  CLAUDE.md
  README.md
  .gitignore
  .env.example
  docker-compose.yml
  .pre-commit-config.yaml      # ruff + flake8 + pyright + prettier + eslint + tsc gates
  apps/
    api/
      pyproject.toml
      pyrightconfig.json
      .flake8
      Dockerfile
      alembic.ini
      migrations/
        env.py
        script.py.mako
        versions/
          0001_initial_schema.py        # consolidated baseline
          0002_seed_tr_geography.py     # 81 provinces + 973 districts
          0003_widen_markets_address.py
          0004_seed_city_scrapers.py    # 9 per-city scraper rows
          0005_page_views.py            # per-path visit counters
          0006_products.py              # products registry
          0007_prices_product_id.py     # product_id FK on every prices_<slug>
          0008_drop_non_produce.py      # drop fish/seafood + orphans
          0009_drop_legacy_price_columns.py  # drop text cols; key on (date, product_id)
          0010_normalize_units_cleanup.py
          0011_normalize_categories.py
          0012_promote_category_words.py
          0013_merge_turp_otu.py
          0014_user_place_suggestions.py     # users + place_suggestions
      src/local_bazaar/
        __init__.py
        main.py               # FastAPI app + lifespan; slowapi rate limit; mounts /api routers
        config.py             # pydantic-settings (env-driven, incl. GOOGLE_MAPS_API_KEY, API_RATE_LIMIT, ADMIN_TOKEN)
        db.py                 # async engine, session, slug helper, per-city Table factory
        models.py             # SQLModel: City, Product, Province, District, Market, MarketType, ScrapeRun, PageView, User, PlaceSuggestion
        geocoding.py          # Google Maps Geocoding wrapper + batch geocode_pending_markets()
        api/
          __init__.py
          prices.py           # GET /cities, /cities/{slug}/prices, /products, /products/{name}/history
          markets.py          # GET /provinces, /provinces/{slug}/districts, /markets
          page_views.py       # POST + GET /page-views
          suggestions.py      # POST /suggestions (add/update a market; pending review)
          admin.py            # token-gated suggestion review: list/approve/reject
        scheduler.py          # apscheduler wiring + run_daily_scrape()
        scrapers/
          __init__.py
          base.py             # ProductPrice, http_client(), fetch_with_retry(), upsert_prices()
          hal_gov_tr.py       # national bulletin scraper (writes to prices_national)
          bazaar_locations.py # markets crawl (provinces × districts × types)
          cities/
            __init__.py
            adana.py          # listing → detail two-layer scraper
            ankara.py         # Laravel POST with CSRF
            antalya.py        # Playwright (Vue SPA)
            bursa.py          # GET ?tarih=YYYY-MM-DD (ISO only)
            istanbul.py       # AJAX gunluk_fiyatlar.asp × 3 categories
            izmir.py          # GET ?date=...&tip=N
            kocaeli.py        # date in URL path
            konya.py          # GET ?tarih=YYYY-MM-DD
            sanliurfa.py      # GET form with start_date/end_date
      tests/
        conftest.py           # async DB fixture (skipped without TEST_DATABASE_URL)
        test_db_slug.py
        test_models.py
        test_scheduler.py
        test_scrapers_normalization.py
        test_scrapers_parsing.py
        test_scrapers_http.py
        test_bazaar_locations.py
        test_geocoding.py
        test_api_prices.py        # integration; needs TEST_DATABASE_URL
        test_api_suggestions.py   # integration; needs TEST_DATABASE_URL
        test_api_admin.py         # integration; needs TEST_DATABASE_URL
    web/
      package.json
      pnpm-lock.yaml           # generated
      next.config.mjs
      tsconfig.json
      tailwind.config.ts       # Stripe-inspired tokens
      postcss.config.mjs
      eslint.config.mjs        # Next.js 16 native flat config
      .prettierrc.json         # + prettier-plugin-tailwindcss
      .prettierignore
      vitest.config.mts
      vitest.setup.ts
      Dockerfile
      public/                       # static assets (created by Dockerfile expectation)
      src/
        app/
          layout.tsx                # SiteHeader + main; AdSense/CMP loaders + PageViewCounter
          page.tsx                  # Linear-style homepage (hero + 3 animated section previews)
          globals.css               # base styles + @keyframes for the home mockups
          prices/page.tsx           # Hal Fiyatları daily bulletin (moved from `/`)
          trends/page.tsx           # historical series: product picker + Hal multiselect + granularity
          products/[name]/page.tsx  # product detail: time-series chart + stats
          markets/page.tsx          # Google Maps view of pazar yerleri + Konumumu Kullan + suggestion form
          admin/                    # hidden, token-gated suggestion review (noindex)
            layout.tsx              # noindex metadata
            suggestions/page.tsx    # token gate + approve/reject list
          privacy/                  # privacy policy (AdSense requirement)
          ads.txt/                  # ads.txt route for AdSense
        components/
          SiteHeader.tsx            # sticky top nav; replaces the old Sidebar
          CitySelector.tsx
          DateSelector.tsx
          RangePresets.tsx
          MultiSelect.tsx           # checkbox dropdown (Hal filter on /trends)
          ProductPicker.tsx         # searchable product combobox (/trends)
          PriceTable.tsx
          PriceChart.tsx            # recharts; solid dots = real, hollow = interpolated
          MarketsMap.tsx            # @vis.gl/react-google-maps wrapper; draft-pin + selectable modes
          SuggestionForm.tsx        # add/update market suggestion modal (/markets)
          PageViewCounter.tsx       # fire-and-forget POST /api/page-views (renders nothing)
          AdSlot.tsx                # AdSense slot (inert when client id is empty)
          home/                     # homepage section previews (CSS-only animations)
            MarketsMockup.tsx
            PricesMockup.tsx
            TrendsMockup.tsx
          *.test.tsx                # vitest co-located with each component
        lib/
          api.ts                    # typed fetch client; defaults to same-origin /api
          cn.ts
          format.ts
          *.test.ts
  deploy/
    k8s/
      base/                      # namespace, deployments, services, ingress, configmaps, cronjob, secrets.example
      overlays/
        dev/                     # dev hostname + ACM cert
        prod/                    # prod hostname + ACM cert + replica overrides
        local/                   # Docker Desktop k8s: pullPolicy: Never, LoadBalancer:8080, inline secrets (gitignored)
```

## Commands

PowerShell-flavored. Run from the repo root. Use `;` for sequencing, not `&&`.

### Local — full stack (preferred path)

```powershell
Copy-Item .env.example .env
# Edit .env and set DATABASE_URL to point at your external Postgres / RDS instance.
docker compose up --build
docker compose exec api alembic upgrade head
```

- API: http://127.0.0.1:8000  (loopback only; OpenAPI at `/docs` because the compose env sets `ENABLE_API_DOCS=1`)
- Web: http://localhost:3000 — browser-side `/api/*` calls are proxied by Next.js to the internal `http://api:8000`
- Database is **not** containerized — set `DATABASE_URL` in `.env` to your RDS endpoint (or any reachable Postgres).

### Backend (`apps/api`) — standalone

```powershell
cd apps/api
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn local_bazaar.main:app --reload
uv run python -m local_bazaar.scrapers.hal_gov_tr        # national bulletin (synthetic 'national' slug)
uv run python -m local_bazaar.scrapers.bazaar_locations  # one-off markets crawl
# Per-city scrapers — default lookback 160 days, skips dates already in prices_<slug>
uv run python -m local_bazaar.scrapers.cities.istanbul
uv run python -m local_bazaar.scrapers.cities.ankara
uv run python -m local_bazaar.scrapers.cities.izmir
uv run python -m local_bazaar.scrapers.cities.bursa
uv run python -m local_bazaar.scrapers.cities.konya
uv run python -m local_bazaar.scrapers.cities.adana
uv run python -m local_bazaar.scrapers.cities.kocaeli
uv run python -m local_bazaar.scrapers.cities.sanliurfa
uv run python -m local_bazaar.scrapers.cities.antalya    # needs `uv sync --extra playwright && playwright install chromium`
# Quality gates (mirrored by .pre-commit-config.yaml)
uv run ruff check src tests
uv run ruff format --check src tests
uv run flake8 src tests
uv run pyright src
uv run pytest                       # set TEST_DATABASE_URL to also run integration tests
```

### Frontend (`apps/web`) — standalone

```powershell
cd apps/web
pnpm install
pnpm dev
pnpm build
# Quality gates (mirrored by .pre-commit-config.yaml)
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
```

### Pre-commit hooks

After `git init`, install once:

```powershell
uv tool install pre-commit       # or: pipx install pre-commit
pre-commit install
```

Every commit then runs ruff (lint + format), flake8, pyright on the backend and prettier / eslint / tsc on the frontend. See `.pre-commit-config.yaml` for the full list.

### Deploy

```powershell
docker build -t local-bazaar/api:<tag> apps/api
docker build --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=$env:NEXT_PUBLIC_GOOGLE_MAPS_API_KEY `
  -t local-bazaar/web:<tag> apps/web
kubectl apply -k deploy/k8s/overlays/dev
kubectl -n local-bazaar-dev rollout status deploy/api deploy/web
```

The web image inlines `NEXT_PUBLIC_*` env at build time (Next.js standalone bakes them into the client bundle), so pass them through `--build-arg`. The api image installs Playwright + Chromium (~150MB) for the Antalya scraper.

### Local Kubernetes — Docker Desktop

`deploy/k8s/overlays/local/` is the overlay for testing against the bundled Docker Desktop cluster. Docker Desktop's k8s uses containerd with the `k8s.io` namespace and does NOT see images built by the Docker daemon (which lives in the `moby` namespace) — every image rebuild must be re-imported:

```powershell
docker build -t local-bazaar/api:local apps/api
docker build --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=$env:NEXT_PUBLIC_GOOGLE_MAPS_API_KEY `
  -t local-bazaar/web:local apps/web

# Import both into the cluster's containerd
docker save local-bazaar/api:local | docker exec -i desktop-control-plane ctr -n k8s.io images import -
docker save local-bazaar/web:local | docker exec -i desktop-control-plane ctr -n k8s.io images import -

# First time: create deploy/k8s/overlays/local/secrets.yaml (gitignored) with real DATABASE_URL + Google Maps key.
kubectl apply -k deploy/k8s/overlays/local
kubectl -n local-bazaar rollout status deploy/api deploy/web

# Migrate (idempotent)
kubectl -n local-bazaar exec deploy/api -- alembic upgrade head

# Web is exposed at http://localhost:8080 via LoadBalancer Service.
```

## Conventions

- **Codebase language is English.** All identifiers, comments, docstrings, log messages, and UI strings are English. Only scraped data values (Turkish product names like "Domates", category enum values like "Geleneksel/Konvansiyonel") remain in Turkish because they come straight from the source. Do not translate scraped data.
- **Mandatory docstrings and type annotations.** Every public Python function, method, and class needs a docstring. Function docstrings follow the **Google convention** and must include `Args:` for every parameter (except `self`/`cls`) and `Returns:` when the function returns a non-trivial value. Every function signature must carry full parameter and return-type annotations. Tests are exempt from `D` rules but still need annotations. These are enforced by ruff + flake8-docstrings + pyright in pre-commit.
- **Per-city tables are sacred**: schema differences between `prices_*` tables are not allowed. Schema changes apply to *every* `prices_*` table in one Alembic migration — iterate over `cities` rows and apply.
- **Prices**: `NUMERIC(12,4)` TRY. In Python use `decimal.Decimal`, never float.
- **Timestamps**: UTC `TIMESTAMPTZ`. Use `datetime.now(timezone.utc)`. Bulletin date (`bulletin_date`) is a `DATE` in Turkey time.
- **Slugs**: `db.city_slug()` only. Don't re-roll Turkish folding.
- **Scrapers**: one module per source under `scrapers/`. Each exposes `async run(session) -> int`. Add new sites without touching anything outside `scrapers/` + a `cities` row.
- **Politeness**: respect robots.txt where the user has not explicitly opted out; set `SCRAPER_USER_AGENT`; small sleep between paginated requests; retry only on network/timeout errors (`tenacity` in `scrapers/base.py`).
- **Scheduler errors**: per-scrape errors must never crash the scheduler. `scheduler._safe_scrape()` records every attempt in `scrape_runs` with status `ok|partial|failed`.
- **API**: public reads need no auth. Mostly read-only; the unauthenticated writes are `POST /api/page-views` (counter) and `POST /api/suggestions` (queued for review, honeypot-guarded). The `/api/admin/*` review endpoints are the one privileged surface, gated by a shared `ADMIN_TOKEN` in the `X-Admin-Token` header (compared constant-time; 503 when unset). Every route is per-IP rate-limited by slowapi. CORS origins are env-driven (`API_CORS_ORIGINS`) but are no longer load-bearing for security — the API is not exposed to the public internet (see Architecture). When adding endpoints that query per-city tables, guard against `prices_<slug>` not yet existing: use `to_regclass(:name)` or the `_existing_slugs(session, slugs)` helper in `api/prices.py`.
- **Frontend types**: hand-maintained in `src/lib/api.ts`. When changing API shapes, update both files in the same PR. Codegen via `openapi-typescript` can be added later — there is intentionally none today.
- **Secrets**: only in `.env` locally and AWS Secrets Manager in cluster. `deploy/k8s/base/secrets.example.yaml` shows the expected shape — never commit real values. The Google Maps key is split into two env vars: server-side `GOOGLE_MAPS_API_KEY` (used by `geocoding.py`) and browser-side `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` (used by the map widget). Restrict each in the Google Cloud Console (IP for server, HTTP referrer for browser). `ADMIN_TOKEN` is the shared secret for the `/admin/suggestions` page — empty disables the admin API; set a long random value locally and in cluster secrets.

## Platform notes

- Development host is **Windows 11**. Use PowerShell syntax (no `&&` chaining; use `;`).
- Python: `pathlib.Path` only — never hard-code `\` or `/`.
- Playwright is **already** in the production image (for Antalya). For host-side ad-hoc runs, `uv sync --extra playwright` then `playwright install chromium` once.
- Docker Desktop on Windows: WSL2 backend. Keep line endings LF for files copied into Linux images — add `.gitattributes` with `* text=auto eol=lf` once git is initialized.

## What to do next

1. **Provision Google Maps** if not already done: enable Maps JavaScript API + Geocoding API in GCP, generate two keys (server / browser), put them in `.env` as `GOOGLE_MAPS_API_KEY` and `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`. Without these, market lat/lng will stay null and the `/markets` page shows a "set the key" placeholder.
2. **Backfills** are idempotent — re-running a city scraper is cheap because each one skips dates already in `prices_<slug>`. Use the per-module CLI commands listed above to seed history (160 days by default).
3. **Add a per-city price scraper**: write `apps/api/src/local_bazaar/scrapers/cities/<slug>.py` mirroring an existing one, then add a new Alembic migration that inserts the row into `cities` (see `0004_seed_city_scrapers.py`). The scheduler auto-discovers it.
4. **Review place suggestions**: visit the hidden `/admin/suggestions` page (gated by `ADMIN_TOKEN`, no nav link) to approve (auto-applies to `markets`) or reject pending rows; or query `place_suggestions` directly in the DB. Set `ADMIN_TOKEN` in `.env` (and cluster secrets) to enable the page.
5. **CI/CD**: GitHub Actions workflows under `.github/workflows/` (lint, test, build images, push to ECR, `kubectl apply -k overlays/<env>`) — not yet scaffolded.
6. **Terraform skeleton** under `deploy/terraform/` (EKS, RDS, ECR, VPC, IAM, External Secrets) — not yet scaffolded.

## Out of scope (today)

- User accounts, multi-tenancy, billing. Public reads need no auth; the only privileged surface is the shared-token `/admin/suggestions` review page (no per-user login).
- Real-time / intraday updates. Daily snapshots only.
- Forecasting / ML on top of the price series.
- Mobile-native clients. Web (responsive) is the only frontend.
