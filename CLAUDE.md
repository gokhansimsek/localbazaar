# CLAUDE.md — Semt Pazarı

Guidance for Claude Code sessions working in this repo.

## Project overview

**Semt Pazarı** is a Turkish neighborhood-markets platform. It ships two features today, with room for more:

1. **Hal Fiyatları** — daily and historical wholesale-market ("hal") prices for agricultural products, sourced from the national `hal.gov.tr` bulletin (and, eventually, per-city sources). Stored per city, per product, per (variety × category) variant.
2. **Pazar Yerleri** — every neighborhood (semt) and producer (üretici) market published by hal.gov.tr, normalized into provinces → districts → markets and geocoded via the Google Maps Geocoding API for display on a map.

A FastAPI backend exposes the data; a Next.js UI renders the dashboards (`/`, `/trends`, `/products/[name]`) for Hal Fiyatları and the map page (`/markets`) for Pazar Yerleri. The system is deployed as containers on AWS via Kubernetes.

### Internal naming

Internal identifiers use `local_bazaar` (snake) / `local-bazaar` (kebab) consistently across code, infra, and storage. **User-visible strings — page titles, sidebar, OpenAPI summary, README — say "Semt Pazarı".**

- `apps/api/src/local_bazaar/` — Python package and all imports
- `apps/api/pyproject.toml` — ``name = "local_bazaar"``
- `deploy/k8s/.../*` — namespace `local-bazaar`, label `app.kubernetes.io/part-of: local-bazaar`
- The Postgres role / DB name is whatever the external Postgres (RDS) is provisioned with; the example URLs in `.env.example` use `local_bazaar` but the application only cares about `DATABASE_URL`.

## Status

Scaffolding is complete and gated by quality tools. The repo has:

- A working monorepo (`apps/api`, `apps/web`, `deploy/k8s`).
- One consolidated Alembic baseline: `0001_initial_schema` (cities + scrape_runs + `prices_national` + provinces + districts + markets). Targets an empty database (e.g. a fresh RDS instance).
- Three scrapers: `hal_gov_tr` (national bulletin), `bazaar_locations` (markets), and a per-city dispatcher under `scrapers/cities/`.
- Google Maps geocoding (`geocoding.py`) and a map page in the Next.js UI.
- 71 backend tests + 35 frontend tests, all green. 8 backend integration tests are auto-skipped without `TEST_DATABASE_URL`.
- Pre-commit hooks enforcing ruff + flake8 + pyright (Python) and prettier + eslint + tsc (TypeScript).

No git yet (the user is initializing git later). When code drifts from this document, trust the code and update this file.

## Domain & data sources

### Primary source — hal.gov.tr

- URL: `https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx`
- ASP.NET WebForms — pagination uses `__doPostBack` against `__VIEWSTATE`/`__EVENTVALIDATION`. The GridView id contains `gvFiyatlar`.
- **No city dropdown on this page** — it is national/aggregate data. We store its rows under the synthetic city slug `national` (seeded by the initial migration; display name `National`).
- Columns (English in DB, with the Turkish source headers for reference):

| Turkish header   | DB column             | Type              |
|------------------|-----------------------|-------------------|
| Ürün Adı         | `product_name`        | TEXT              |
| Ürün Cinsi       | `product_variety`     | TEXT (nullable)   |
| Ürün Türü        | `product_category`    | TEXT (Geleneksel/Konvansiyonel \| İyi Tarım \| Organik Tarım — stored verbatim from the source) |
| Ortalama Fiyat   | `average_price`       | NUMERIC(12,4) TRY |
| İşlem Hacmi      | `transaction_volume`  | BIGINT (nullable) |
| Birim Adı        | `unit_name`           | TEXT (Kg \| Adet) |

### Secondary source — city-level prices via Google

- Per-city hal sites are not aggregated on hal.gov.tr.
- Strategy: Google search for `"hal fiyatları" <şehir>` to discover per-city sources, then add a dedicated module at `apps/api/src/local_bazaar/scrapers/cities/<sehir>.py` exposing `async run(session) -> int`.
- Discovery is a **manual, one-time step per city**; scrapers themselves do not call Google at runtime.

### Tertiary source — pazar yerleri (markets)

- URL: `https://www.hal.gov.tr/Sayfalar/Pazar-Yerleri.aspx`
- ASP.NET WebForms search: select il (`ddlIl`), ilçe (`ddlIlce`), and market type (`ddlTur`), then submit `BtnAra`. Submitting fires postbacks with the GUID-prefixed control names `ctl00$ctl37$g_<guid>$<leaf>`.
- The crawler iterates every province × district × market-type combination, parses the result block, and UPSERTs into `markets` referencing `districts` and `provinces` by FK.
- Two market types are recognized: `Semt Pazarı` (neighborhood) and `Üretici Pazarı` (producer).
- The scraper itself never calls Google. After scraping, geocoding is opt-in via `scripts/geocode_markets.py` (which delegates to `local_bazaar.geocoding`) to fill in `latitude` / `longitude` for any markets with NULL coordinates. The same API key powers the frontend map widget (`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`).

### Update cadence

- Daily scrape at 02:00 Europe/Istanbul.
- In-cluster, the CronJob `scrape-daily` is the canonical trigger (the in-process apscheduler is disabled via `SCRAPER_DISABLE_SCHEDULER=1`).
- Locally / in `docker compose`, the in-process scheduler runs.

## Database schema

PostgreSQL 17. The schema has three concerns: per-city price tables, normalized geography (provinces → districts → markets), and audit / registry tables.

### Per-city prices

- `prices_<city_slug>` (e.g. `prices_national`, `prices_istanbul`).
- Identical columns + unique constraint `(bulletin_date, product_name, product_variety, product_category, unit_name)` to make UPSERTs idempotent.
- Registry: `cities (id, slug, name, source_type, source_url, enabled, created_at)`.
- Cross-city queries use UNION ALL over registered tables. There is **also** a SQL-generated UNION pattern in `api/prices.py::product_history` and a helper `db.rebuild_prices_view()` that can (re)create a `prices_all` view if you prefer querying through it.

### Geography + markets

- `provinces (id, slug, name, plate_code, created_at)` — one row per Turkish il.
- `districts (id, province_id FK, slug, name, created_at)` — one row per ilçe, PK/FK to provinces.
- `markets (id, district_id FK, market_type, name, address, day_of_week, latitude, longitude, geocoded_at, last_seen, created_at)` — one row per physical market.
- Unique on `(district_id, market_type, name)` for idempotent UPSERTs (the scraper folds parenthetical sub-sections like `"... (BALIK BÖLÜMÜ)"` into the same logical market).
- `latitude`/`longitude` are populated by `scripts/geocode_markets.py` (which calls `local_bazaar.geocoding`), not by the scraper itself or by the daily scheduler.

### Audit

- `scrape_runs (scraper, city_slug, bulletin_date, status, rows_written, error, started_at, finished_at)` — UI staleness banners can read from this.

The slug helper is `db.city_slug()` — Turkish-aware ASCII folding (`İstanbul → istanbul`, `Şanlıurfa → sanliurfa`). Do not re-implement.

## Architecture

```
[Next.js UI]  ──HTTP──>  [FastAPI API]  ──SQL──>  [PostgreSQL]
                              │
       Local dev only ────────┴── apscheduler ──> [Scrapers]

       In cluster: CronJob `scrape-daily` ─────> [Scrapers]
```

- Scrapers live inside the API package and are reused by both the in-process scheduler (dev) and the CronJob (prod).

## Tech stack (established)

### Backend — `apps/api`

- **Python 3.14** (latest stable, May 2026). `requires-python = ">=3.14"`.
- FastAPI + `uvicorn[standard]`, `pydantic-settings`
- SQLModel + SQLAlchemy 2.x async, `psycopg[binary]` driver
- Alembic for migrations (registry tables tracked; per-city `prices_*` tables created via raw DDL helpers in `db.ensure_city_table()`)
- `httpx` + `selectolax` for scraping; `tenacity` for retries; `playwright` is an optional extra (`uv sync --extra playwright`) reserved for sites that need JS rendering
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
- Date / number formatting via Intl in `src/lib/format.ts`
- API client is hand-typed in `src/lib/api.ts` (no codegen yet — keep types in sync with the Pydantic models in `apps/api/src/local_bazaar/api/`)
- Quality: **eslint** (Next.js 16 native flat config in `eslint.config.mjs`), **prettier** (with `prettier-plugin-tailwindcss`), **tsc --noEmit**, **vitest** + `@testing-library/react` + `msw`

### Infra

- Docker: multi-stage per service. API uses `python:3.14-slim` + `uv`; Web uses `node:20-alpine` + `pnpm` + Next.js standalone output.
- Kubernetes: Kustomize under `deploy/k8s/{base,overlays/{dev,prod}}` — Deployments (api, web), Services, ALB Ingress, ConfigMaps, CronJob, plus a `secrets.example.yaml` for shape (do **not** commit real Secrets).
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
          0001_initial_schema.py  # consolidated baseline
      src/local_bazaar/
        __init__.py
        main.py               # FastAPI app + lifespan; mounts /api router
        config.py             # pydantic-settings (env-driven, incl. GOOGLE_MAPS_API_KEY)
        db.py                 # async engine, session, slug helper, per-city Table factory
        models.py             # SQLModel: City, Province, District, Market, MarketType, ScrapeRun
        geocoding.py          # Google Maps Geocoding wrapper + batch geocode_pending_markets()
        api/
          __init__.py
          prices.py           # GET /cities, /cities/{slug}/prices, /products/{name}/history
          markets.py          # GET /provinces, /provinces/{slug}/districts, /markets
        scheduler.py          # apscheduler wiring + run_daily_scrape()
        scrapers/
          __init__.py
          base.py             # ProductPrice, http_client(), fetch_with_retry(), upsert_prices()
          hal_gov_tr.py       # national bulletin scraper (writes to prices_national)
          bazaar_locations.py # markets crawl (provinces × districts × types)
          cities/             # per-city price scrapers (one module per city slug)
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
        test_api_prices.py    # integration; needs TEST_DATABASE_URL
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
      src/
        app/
          layout.tsx
          page.tsx              # daily bulletin table (home)
          globals.css
          products/[name]/page.tsx  # product detail: time-series chart + stats
          markets/page.tsx          # Google Maps view of pazar yerleri
        components/
          Sidebar.tsx
          CitySelector.tsx
          DateSelector.tsx
          RangePresets.tsx
          PriceTable.tsx
          PriceChart.tsx
          MarketsMap.tsx           # @vis.gl/react-google-maps wrapper
          *.test.tsx               # vitest co-located with each component
        lib/
          api.ts                   # typed fetch client (cities, prices, history, provinces, districts, markets)
          cn.ts
          format.ts
          *.test.ts
  deploy/
    k8s/
      base/                      # namespace, deployments, services, ingress, configmaps, cronjob, secrets.example
      overlays/{dev,prod}/       # image tags + host + ACM cert per env
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

- API: http://localhost:8000  (OpenAPI: `/docs`)
- Web: http://localhost:3000
- Database is **not** containerized — set `DATABASE_URL` in `.env` to your RDS endpoint (or any reachable Postgres).

### Backend (`apps/api`) — standalone

```powershell
cd apps/api
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn local_bazaar.main:app --reload
uv run python -m local_bazaar.scrapers.hal_gov_tr      # one-off price scrape
uv run python -m local_bazaar.scrapers.bazaar_locations  # one-off markets crawl
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
docker build -t local-bazaar/web:<tag> apps/web
kubectl apply -k deploy/k8s/overlays/dev
kubectl -n local-bazaar-dev rollout status deploy/api deploy/web
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
- **API**: read-only, no auth. CORS origins are env-driven (`API_CORS_ORIGINS`).
- **Frontend types**: hand-maintained in `src/lib/api.ts`. When changing API shapes, update both files in the same PR. Codegen via `openapi-typescript` can be added later — there is intentionally none today.
- **Secrets**: only in `.env` locally and AWS Secrets Manager in cluster. `deploy/k8s/base/secrets.example.yaml` shows the expected shape — never commit real values. The Google Maps key is split into two env vars: server-side `GOOGLE_MAPS_API_KEY` (used by `geocoding.py`) and browser-side `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` (used by the map widget). Restrict each in the Google Cloud Console (IP for server, HTTP referrer for browser).

## Platform notes

- Development host is **Windows 11**. Use PowerShell syntax (no `&&` chaining; use `;`).
- Python: `pathlib.Path` only — never hard-code `\` or `/`.
- If `playwright` is added: after `uv sync --extra playwright`, run `playwright install chromium` once.
- Docker Desktop on Windows: WSL2 backend. Keep line endings LF for files copied into Linux images — add `.gitattributes` with `* text=auto eol=lf` once git is initialized.

## What to do next

1. **Initialize git** (`git init`) — natural next move. Add `.gitattributes` (`* text=auto eol=lf`) at the same time, then `pre-commit install` to wire the hooks.
2. **Provision Google Maps**: create a Google Cloud project, enable Maps JavaScript API + Geocoding API, generate two keys (server / browser), and put them in `.env` as `GOOGLE_MAPS_API_KEY` and `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`. Without these, market lat/lng will stay null and the `/markets` page shows a "set the key" placeholder.
3. **First `docker compose up --build`** to validate Postgres + API + Web come up green. Then `docker compose exec api uv run alembic upgrade head` to apply both migrations.
4. **First real scrapes**:
   - `docker compose exec api uv run python -m local_bazaar.scrapers.hal_gov_tr` — should populate `prices_national`.
   - `docker compose exec api uv run python -m local_bazaar.scrapers.bazaar_locations` — should populate `provinces`, `districts`, `markets`. Long-running (~30–60 min for all 81 provinces).
   - The bazaar-locations scraper has only been parser-tested; the live form may need a selector tweak on the result block (see `_parse_markets` fallback list).
5. **Add a per-city price scraper** under `apps/api/src/local_bazaar/scrapers/cities/<slug>.py`. Register the city in the `cities` table (or via a migration) and let the scheduler pick it up.
6. **CI/CD**: GitHub Actions workflows under `.github/workflows/` (lint, test, build images, push to ECR, `kubectl apply -k overlays/<env>`) — not yet scaffolded.
7. **Terraform skeleton** under `deploy/terraform/` (EKS, RDS, ECR, VPC, IAM, External Secrets) — not yet scaffolded.

## Out of scope (today)

- Auth, multi-tenancy, billing. App exposes read-only price data.
- Real-time / intraday updates. Daily snapshots only.
- Forecasting / ML on top of the price series.
- Mobile-native clients. Web (responsive) is the only frontend.
