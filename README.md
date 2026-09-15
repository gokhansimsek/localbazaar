# Local Bazaar

A platform for Turkey's neighborhood bazaars. The first feature is **Wholesale Market Prices** (daily and historical produce prices collected from the `hal.gov.tr` national bulletin and per-city sources). The second feature is the **Bazaar Map** (neighborhood and producer markets in every province/district on Google Maps). Data is stored in PostgreSQL, served by FastAPI, and rendered by a Next.js frontend.

## Features

- **Wholesale Market Prices** — daily national bulletin plus 9 per-city scrapers (Adana, Ankara, Antalya, Bursa, Istanbul, Izmir, Kocaeli, Konya, Şanlıurfa). Scraped descriptors are normalized into a shared `products` registry (canonical category/unit; fish/seafood excluded). A `/trends` page offers a searchable product picker, a Hal (city) multiselect filter, daily/weekly/monthly granularity, and optional least-squares gap-fill; per-product detail pages add statistics cards across time windows (Today / Last week / Last month / Last 3 months / Last year / All).
- **Bazaar Map** — neighborhood and producer markets for every province/district in Turkey, geocoded as pins on Google Maps. Includes a "Konumumu Kullan" geolocation helper that auto-fills both province and district from the browser's location, plus a suggestion form where visitors can propose a new market (drop a pin) or a correction to an existing one. Submissions are reviewed on a hidden, token-gated `/admin/suggestions` page where an operator approves them (auto-applied to the map) or rejects them.

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
# ADMIN_TOKEN (optional) enables the hidden /admin/suggestions review page; leave empty to disable it.
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
  - `/admin/suggestions` — hidden, token-gated review page (no nav link; needs `ADMIN_TOKEN`)
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

## Running the scrapers

There are **eleven** scrapers, all living inside the API package under
`apps/api/src/local_bazaar/scrapers/`. Every concrete scraper exposes
`async run(session) -> int` (returns the number of rows written) and can be
driven three ways: as a one-off CLI module (`python -m …`), by the in-process
`apscheduler` (local/dev only), or by the Kubernetes `scrape-daily` CronJob.

| Scraper module | What it does | Writes to | Default lookback | Typical runtime |
|----------------|--------------|-----------|------------------|-----------------|
| `scrapers.hal_gov_tr` | National `hal.gov.tr` bulletin | `prices_national` | 360 days | ~1 h cold, seconds warm |
| `scrapers.cities.<slug>` | Per-city hal prices (9 cities) | `prices_<slug>` | 160 days | minutes; cheap warm |
| `scrapers.bazaar_locations` | Markets crawl (81 il × ilçe × type) | `provinces`/`districts`/`markets` | n/a (full crawl) | ~30–60 min |
| `scripts/geocode_markets.py` | Fills `latitude`/`longitude` (Google API) | `markets` | n/a (opt-in) | depends on `--max` |

City slugs: `adana`, `ankara`, `antalya`, `bursa`, `istanbul`, `izmir`,
`kocaeli`, `konya`, `sanliurfa`.

**Idempotency** — every scrape is safe to re-run. The price scrapers skip any
`bulletin_date` already present in their `prices_<slug>` table, so repeat runs
only fetch missing days. The markets crawl UPSERTs on
`(district_id, market_type, name)`. Geocoding only touches rows whose
coordinates are still `NULL`.

**Geocoding is never automatic.** It is excluded from both the scheduler and the
CronJob because it spends Google Maps API quota. Run `scripts/geocode_markets.py`
by hand after a markets crawl (see below).

### Scraper-related environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `DATABASE_URL` | — (required) | Async Postgres DSN the scrapers write to. |
| `SCRAPER_USER_AGENT` | `local_bazaar/0.1` | `User-Agent` sent on every scrape request. |
| `SCRAPER_DAILY_HOUR` | `2` | Hour (Europe/Istanbul) the in-process scheduler fires. |
| `SCRAPER_DISABLE_SCHEDULER` | `false` | Set to `1`/`true` to suppress the in-process scheduler (set in-cluster, where the CronJob owns scheduling). |
| `GOOGLE_MAPS_API_KEY` | — | Server-side key used only by `scripts/geocode_markets.py` (not by the scrapers themselves). |

The lookback windows are constructor arguments inside each scraper module
(`_DEFAULT_LOOKBACK_DAYS`), not environment variables — to backfill a longer
window, edit the default or instantiate the scraper class directly in a REPL.

### Running locally

**Option A — standalone (`uv`), fastest feedback loop.** Run from `apps/api`
with `DATABASE_URL` set in your environment (or an `apps/api/.env`):

```powershell
cd apps/api
uv sync --extra dev
uv run alembic upgrade head        # schema must exist before the first scrape

# National bulletin (synthetic 'national' slug). First run backfills ~360 days (~1 h);
# subsequent runs only fetch the 1–2 missing days, so they finish in seconds.
uv run python -m local_bazaar.scrapers.hal_gov_tr

# Per-city price scrapers (default lookback 160 days; skip dates already stored).
uv run python -m local_bazaar.scrapers.cities.istanbul
uv run python -m local_bazaar.scrapers.cities.ankara
uv run python -m local_bazaar.scrapers.cities.izmir
uv run python -m local_bazaar.scrapers.cities.bursa
uv run python -m local_bazaar.scrapers.cities.konya
uv run python -m local_bazaar.scrapers.cities.adana
uv run python -m local_bazaar.scrapers.cities.kocaeli
uv run python -m local_bazaar.scrapers.cities.sanliurfa

# Antalya needs Playwright + Chromium (the source is a Vue SPA):
uv sync --extra playwright
playwright install chromium
uv run python -m local_bazaar.scrapers.cities.antalya

# Markets crawl (long; no Google calls). Then geocode opt-in.
uv run python -m local_bazaar.scrapers.bazaar_locations
uv run python scripts/geocode_markets.py --max=200
```

**Option B — through Docker Compose** (scrapers run inside the already-built API
container, same image as production):

```powershell
docker compose up --build
docker compose exec api alembic upgrade head
docker compose exec api python -m local_bazaar.scrapers.hal_gov_tr
docker compose exec api python -m local_bazaar.scrapers.cities.istanbul
# …same module names as Option A; Playwright/Chromium are already baked into the image.
docker compose exec api python -m local_bazaar.scrapers.bazaar_locations
docker compose exec api python scripts/geocode_markets.py --max=200
```

**Option C — let the in-process scheduler do it.** Whenever the API runs locally
(standalone `uvicorn` or `docker compose`) and `SCRAPER_DISABLE_SCHEDULER` is not
set, an `apscheduler` job fires `run_daily_scrape()` at `SCRAPER_DAILY_HOUR:00`
Europe/Istanbul (default 02:00). That single job runs the national scraper, **all**
enabled per-city scrapers (auto-discovered from the `cities` table), and the
markets crawl — but **not** geocoding. Every attempt is recorded in `scrape_runs`
with status `ok` / `partial` / `failed`; one source failing never aborts the rest.

### Running on the cloud (Kubernetes / EKS)

In-cluster, the in-process scheduler is **disabled** (`SCRAPER_DISABLE_SCHEDULER=1`
on the api Deployment) so the API pods never scrape. Scheduling is owned by a
dedicated `CronJob` (`deploy/k8s/base/scrape-cronjob.yaml`) that runs the same
API image with an overridden command:

```yaml
schedule: "0 23 * * *"     # 02:00 Europe/Istanbul = 23:00 UTC
concurrencyPolicy: Forbid   # never overlap runs
backoffLimit: 2
activeDeadlineSeconds: 7200
command: ["python", "-m", "local_bazaar.scheduler"]
```

`python -m local_bazaar.scheduler` runs `run_daily_scrape()` once and exits, so
the CronJob covers the **same** work as the in-process scheduler: national
bulletin + all 9 per-city scrapers + the markets crawl. Geocoding is still
excluded (run `scripts/geocode_markets.py` on demand). Because the full run
includes the ~30–60 min markets crawl and the Antalya Playwright/Chromium scrape,
the Job allows 2 h (`activeDeadlineSeconds: 7200`) and a 1Gi memory limit.

**Manual / ad-hoc cluster runs** — exec into a running API pod (the scheduler is
off, so this is the way to trigger a scrape on demand):

```powershell
# Replace the namespace with your overlay's (local-bazaar-dev / -prod, or local-bazaar).
kubectl -n local-bazaar-dev exec deploy/api -- python -m local_bazaar.scrapers.cities.istanbul
kubectl -n local-bazaar-dev exec deploy/api -- python -m local_bazaar.scrapers.bazaar_locations
kubectl -n local-bazaar-dev exec deploy/api -- python scripts/geocode_markets.py --max=500
```

**Trigger the daily CronJob immediately** (creates an out-of-schedule Job from the
CronJob template, then watch it):

```powershell
kubectl -n local-bazaar-dev create job --from=cronjob/scrape-daily scrape-manual-001
kubectl -n local-bazaar-dev get jobs -w
kubectl -n local-bazaar-dev logs job/scrape-manual-001 -f
```

**Inspect history** — every CronJob run (and every scrape, however triggered) is
auditable:

```powershell
# Last few CronJob pods + their logs
kubectl -n local-bazaar-dev get pods -l job-name --sort-by=.metadata.creationTimestamp
kubectl -n local-bazaar-dev logs <scrape-pod-name>

# Structured audit trail in Postgres (status ok/partial/failed, rows_written, error)
docker compose exec api psql "$DATABASE_URL" -c \
  "SELECT scraper, city_slug, status, rows_written, finished_at FROM scrape_runs ORDER BY started_at DESC LIMIT 20;"
```

The CronJob image must be present in your registry (ECR) and referenced by the
overlay; building/pushing it is covered under **Deploy** in `CLAUDE.md`. The image
ships Playwright + Chromium so the Antalya scraper works the same in-cluster as
locally.

## Quality gates

Both backend and frontend go through pre-commit hooks. Backend: **ruff** (lint + format), **flake8** (bugbear + comprehensions + docstrings), **pyright**, **pytest**. Frontend: **prettier**, **eslint** (Next.js 16 flat config), **tsc**, **vitest**. See `.pre-commit-config.yaml` for details.

### Running the backend integration tests locally

`test_api_prices.py`, `test_api_suggestions.py`, and `test_api_admin.py` need a real PostgreSQL reachable at `TEST_DATABASE_URL` — they're skipped otherwise. `docker-compose.test.yml` at the repo root spins up a disposable Postgres 17 just for this (never RDS, never your dev database):

```powershell
docker compose -f docker-compose.test.yml up -d
$env:TEST_DATABASE_URL = "postgresql+psycopg://local_bazaar_test:local_bazaar_test@localhost:5433/local_bazaar_test"
cd apps/api
uv run pytest    # the db_session fixture creates + drops its own tables per test — no seeding needed
```

Data lives on tmpfs, so `docker compose -f docker-compose.test.yml down` (or `restart test-db`) wipes it. pytest expects an **empty** database: seeded rows break its assertions and its teardown drops the tables. If you've seeded it for manual exploration (below), restart the container before running pytest.

To instead point the running API/web stack at this database for manual exploration with a small mock dataset (a few products with a week of price history, a handful of geocoded markets) — instead of waiting on real scrapers or Google geocoding quota — run migrations and the seed script against the same URL via `DATABASE_URL` (not `TEST_DATABASE_URL`, which only the pytest fixture reads):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://local_bazaar_test:local_bazaar_test@localhost:5433/local_bazaar_test"
uv run alembic upgrade head
uv run python scripts/seed_test_db.py
uv run uvicorn local_bazaar.main:app --reload
```

Ad-hoc runs:

```powershell
# Backend
cd apps/api
uv run ruff check src tests
uv run ruff format --check src tests
uv run flake8 src tests
uv run pyright src
uv run pytest                      # integration tests (prices/suggestions/admin) also run when TEST_DATABASE_URL is set

# Frontend
cd apps/web
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test                          # ~44 tests across 8 suites
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
