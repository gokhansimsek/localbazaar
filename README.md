# Local Bazaar

A platform for Turkey's neighborhood bazaars. The first feature is **Wholesale Market Prices** (daily and historical produce prices collected from the `hal.gov.tr` national bulletin and per-city sources). The second feature is the **Bazaar Map** (neighborhood and producer markets in every province/district on Google Maps). Data is stored in PostgreSQL, served by FastAPI, and rendered by a Next.js frontend.

## Features

- **Wholesale Market Prices** — daily national bulletin plus 9 per-city scrapers (Adana, Ankara, Antalya, Bursa, Istanbul, Izmir, Kocaeli, Konya, Şanlıurfa). Scraped descriptors are normalized into a shared `products` registry (canonical category/unit; fish/seafood excluded). A `/trends` page offers a searchable product picker, a Hal (city) multiselect filter, daily/weekly/monthly granularity, and optional least-squares gap-fill; per-product detail pages add statistics cards across time windows (Today / Last week / Last month / Last 3 months / Last year / All).
- **Bazaar Map** — neighborhood and producer markets for every province/district in Turkey, geocoded as pins on Google Maps. Includes a "Konumumu Kullan" geolocation helper that auto-fills both province and district from the browser's location, plus a suggestion form where visitors can propose a new market (drop a pin) or a correction to an existing one (queued for manual review).

## Architecture

- **`apps/api`** — FastAPI (Python 3.14), SQLModel + Alembic, scraping with `httpx` + `selectolax` (plus Playwright for the Antalya scraper which targets a Vue SPA), daily job via `apscheduler`, market coordinates via Google Geocoding, per-IP rate limiting via `slowapi`, structured logging via `structlog`.
- **`apps/web`** — Next.js 16 (App Router, TypeScript) + React 19, TailwindCSS (Stripe-inspired palette), `recharts`, `@vis.gl/react-google-maps`, `react-day-picker`. Linear-style landing page with embedded animated UI mockups; sticky top header (no sidebar). Optional Google AdSense + Funding Choices CMP (inert unless configured).
- **PostgreSQL 17** — a shared `products` registry, per-city `prices_<slug>` price tables keyed on `(bulletin_date, product_id)` (created on demand by the first successful scrape), normalized `provinces` / `districts` / `markets` (for the map), `page_views` counters, and `users` / `place_suggestions` (crowdsourced market suggestions).
- **API privacy** — the API is not publicly exposed. Browser calls hit same-origin `/api/*` on the web service; Next.js proxies them to the internal API via `API_INTERNAL_URL`. In Docker the API port is bound to `127.0.0.1`; in Kubernetes the API Service is `ClusterIP` and the Ingress only routes `/`. `/docs`, `/redoc`, and `/openapi.json` are gated behind `ENABLE_API_DOCS` (off by default). Every `/api/*` route is per-IP rate-limited (`API_RATE_LIMIT`, default `120/minute`).
- **Deploy** — Docker images + Kustomize manifests with overlays for `dev`, `prod`, and `local` (Docker Desktop k8s); target stack is AWS EKS + RDS + ECR + Secrets Manager.

> **Note (naming)**: Internal identifiers (Python package, k8s namespace, image names) use `local_bazaar` / `local-bazaar`. All user-facing copy is **Semt Pazarı**.

For more detail see `CLAUDE.md` (DB schema, scraper contract, English-only code rule, Turkish UI rule, docstring + type annotation policy).

## Local development

Initial setup:

```powershell
Copy-Item .env.example .env
# GOOGLE_MAPS_API_KEY (server) and NEXT_PUBLIC_GOOGLE_MAPS_API_KEY (browser) can be filled in.
# If left empty, geocoding is skipped and the /markets page shows a placeholder.
docker compose up --build
```

Services:

- API:  http://127.0.0.1:8000  (bound to loopback only; OpenAPI at `/docs` when `ENABLE_API_DOCS=1`, which is the docker-compose dev default)
- Web:  http://localhost:3000  with routes:
  - `/`           — Linear-style landing page with animated section previews
  - `/prices`     — Hal Fiyatları daily bulletin (Ulusal + 9 cities)
  - `/trends`     — Historical price series (product picker, Hal multiselect, granularity, gap-fill)
  - `/products/[name]` — Per-product detail page
  - `/markets`    — Google Maps view of pazar yerleri + suggestion form
  - `/privacy`    — Privacy policy (AdSense requirement)

The database is **not** containerized — set `DATABASE_URL` in `.env` to an external Postgres (AWS RDS or any reachable instance) before bringing up the stack.

Migrations:

```powershell
docker compose exec api alembic upgrade head
```

Manual scrapes:

```powershell
# National bulletin — backfills the last 360 days that are missing
# (single-day runs are quick; first-time full backfills take ~1 hour).
docker compose exec api python -m local_bazaar.scrapers.hal_gov_tr

# Per-city price scrapers — default lookback is 160 days from today
# (each skips dates already in its prices_<slug> table, so repeat runs are cheap).
docker compose exec api python -m local_bazaar.scrapers.cities.istanbul
docker compose exec api python -m local_bazaar.scrapers.cities.ankara
# ...same pattern for: izmir, bursa, konya, adana, kocaeli, sanliurfa, antalya

# Bazaar locations (81 provinces × districts × type — long, ~30–60 min).
# Stores raw addresses in Title Case. Does NOT call Google geocoding.
docker compose exec api python -m local_bazaar.scrapers.bazaar_locations

# Geocoding is a separate, opt-in script (spends Google API quota).
docker compose exec api python scripts/geocode_markets.py --max=200
```

The Antalya scraper drives a headless Chromium via Playwright (the source is a Vue SPA), so the API image now ships with Playwright + Chromium baked in — about 555MB compressed. The other 8 city scrapers are plain `httpx` + `selectolax`.

The in-container scheduler runs every scraper daily at 02:00 Europe/Istanbul. On Kubernetes the same job is handled by the `scrape-daily` CronJob (`SCRAPER_DISABLE_SCHEDULER=1`).

### Deploying to local Kubernetes (Docker Desktop)

There is a ready-made overlay at `deploy/k8s/overlays/local/` that:

- Sets `imagePullPolicy: Never` on every container so the cluster uses locally-built images.
- Patches the web `Service` to `LoadBalancer` on port `8080` (Docker Desktop publishes this on `localhost:8080`).
- Drops the Ingress (no controller installed by default).
- Reads the API DB URL + Google Maps key from a sibling `secrets.yaml` (gitignored).

```powershell
# Build both images, then import them into the cluster's containerd namespace
# because Docker Desktop's k8s uses a separate image store from Docker.
docker build -t local-bazaar/api:local apps/api
docker build --build-arg NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=$env:NEXT_PUBLIC_GOOGLE_MAPS_API_KEY `
  -t local-bazaar/web:local apps/web
docker save local-bazaar/api:local | docker exec -i desktop-control-plane ctr -n k8s.io images import -
docker save local-bazaar/web:local | docker exec -i desktop-control-plane ctr -n k8s.io images import -

kubectl apply -k deploy/k8s/overlays/local
kubectl -n local-bazaar rollout status deploy/api deploy/web
# Web → http://localhost:8080
```

## Quality gates

Both backend and frontend go through pre-commit hooks. Backend: **ruff** (lint + format), **flake8** (bugbear + comprehensions + docstrings), **pyright**, **pytest**. Frontend: **prettier**, **eslint** (Next.js 16 flat config), **tsc**, **vitest**. See `.pre-commit-config.yaml` for details.

Ad-hoc runs:

```powershell
# Backend
cd apps/api
uv run ruff check src tests
uv run ruff format --check src tests
uv run flake8 src tests
uv run pyright src
uv run pytest                      # ~69 tests; integration tests also run when TEST_DATABASE_URL is set

# Frontend
cd apps/web
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test                          # ~42 tests across 8 suites
```

One-time setup (after cloning):

```powershell
uv tool install pre-commit
pre-commit install
```

## Directory layout

```
apps/api/         FastAPI backend (Python 3.14, uv)  — package: local_bazaar
apps/web/         Next.js frontend (TypeScript, pnpm)
deploy/k8s/       Kustomize manifests (base + overlays/{dev,prod,local})
.pre-commit-config.yaml
```

## Conventions

- **Code language: English** — all identifiers, comments, and docstrings are in English. **UI language: Turkish** — every user-facing string is in Turkish (top header, headings, buttons, error messages).
- **Docstrings + type annotations are mandatory** — Google convention with `Args:` / `Returns:`; enforced in pre-commit by ruff + flake8 + pyright.
- **Prices** are stored as `NUMERIC(12,4)` TRY; `decimal.Decimal` on the Python side, string-typed decimal on the TS side.
- **Per-city price tables** share a single schema; schema changes are applied to every `prices_*` table by a single Alembic migration.
- **Secrets** are not committed — `.env` locally, AWS Secrets Manager + External Secrets Operator in the cluster.

## License

Personal project — no license declared yet.
