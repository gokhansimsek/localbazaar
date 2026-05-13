# Local Bazaar

A platform for Turkey's neighborhood bazaars. The first feature is **Wholesale Market Prices** (daily and historical produce prices collected from the `hal.gov.tr` national bulletin and city-level sources). The second feature is the **Bazaar Map** (neighborhood and producer markets in every province/district on Google Maps). Data is stored in PostgreSQL, served by FastAPI, and rendered by a Next.js frontend.

## Features

- **Wholesale Market Prices** — daily national bulletin, multi-select by product and city, per-product historical chart (separate series by variety and production method), and statistics cards across five time windows (Today / Last week / Last month / Last 3 months / Last year / All).
- **Bazaar Map** — neighborhood and producer markets for every province/district in Turkey, geocoded as pins on Google Maps.

## Architecture

- **`apps/api`** — FastAPI (Python 3.14), SQLModel + Alembic, scraping with `httpx` + `selectolax`, daily job via `apscheduler`, market coordinates via Google Geocoding.
- **`apps/web`** — Next.js 16 (App Router, TypeScript) + React 19, TailwindCSS (Stripe-inspired palette), `recharts`, `@vis.gl/react-google-maps`.
- **PostgreSQL 17** — per-city `prices_<slug>` price tables plus normalized `provinces` / `districts` / `markets` (for the map).
- **Deploy** — Docker images + Kustomize manifests; target stack is AWS EKS + RDS + ECR + Secrets Manager.

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

- API:  http://localhost:8000  (OpenAPI: `/docs`)
- Web:  http://localhost:3000  (`/`, `/trends`, `/products/[name]`, `/markets`)

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

# Bazaar locations (81 provinces × districts × type — long, ~30–60 min).
# Stores raw addresses in Title Case. Does NOT call Google geocoding.
docker compose exec api python -m local_bazaar.scrapers.bazaar_locations

# Geocoding is a separate, opt-in script (spends Google API quota).
docker compose exec api python scripts/geocode_markets.py --max=200
```

The in-container scheduler runs every scraper daily at 02:00 Europe/Istanbul. On Kubernetes the same job is handled by the `scrape-daily` CronJob (`SCRAPER_DISABLE_SCHEDULER=1`).

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
uv run pytest                      # 79 tests; integration tests also run when TEST_DATABASE_URL is set

# Frontend
cd apps/web
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test                          # 38 tests
```

One-time setup after `git init`:

```powershell
uv tool install pre-commit
pre-commit install
```

## Directory layout

```
apps/api/         FastAPI backend (Python 3.14, uv)  — package: local_bazaar
apps/web/         Next.js frontend (TypeScript, pnpm)
deploy/k8s/       Kustomize manifests (base + overlays/{dev,prod})
.pre-commit-config.yaml
```

## Conventions

- **Code language: English** — all identifiers, comments, and docstrings are in English. **UI language: Turkish** — every user-facing string is in Turkish (sidebar, headings, buttons, error messages).
- **Docstrings + type annotations are mandatory** — Google convention with `Args:` / `Returns:`; enforced in pre-commit by ruff + flake8 + pyright.
- **Prices** are stored as `NUMERIC(12,4)` TRY; `decimal.Decimal` on the Python side, string-typed decimal on the TS side.
- **Per-city price tables** share a single schema; schema changes are applied to every `prices_*` table by a single Alembic migration.
- **Secrets** are not committed — `.env` locally, AWS Secrets Manager + External Secrets Operator in the cluster.

## License

Personal project — no license declared yet.
