"""Seed a disposable database with a small, realistic mock dataset.

Intended for the ephemeral Postgres started by ``docker-compose.test.yml``
at the repo root (``TEST_DATABASE_URL``) — never point this at RDS or any
database that matters. It seeds just enough data (a few products with a
week of price history across two cities, and a handful of geocoded markets)
to click around the API or the web UI without waiting on real scrapers or
Google geocoding quota.

The automated integration tests under ``tests/test_api_*.py`` do NOT need
this script — their ``db_session`` fixture creates and seeds its own tables
per test and drops them afterward. This script is for manual exploration
only.

Invocation (from ``apps/api``, with ``DATABASE_URL`` pointed at the test DB —
this script and Alembic both read ``DATABASE_URL``, not ``TEST_DATABASE_URL``):

    docker compose -f ../../docker-compose.test.yml up -d
    export DATABASE_URL=postgresql+psycopg://local_bazaar_test:local_bazaar_test@localhost:5433/local_bazaar_test
    uv run alembic upgrade head   # creates products/cities/geography tables
    uv run python scripts/seed_test_db.py

Safe to re-run: price rows upsert on ``(bulletin_date, product_id)`` and
products upsert on their normalized tuple, so re-running only refreshes
prices. Markets are NOT deduplicated across runs beyond their own
``(district_id, market_type, name)`` unique constraint, which the mock
names here satisfy — re-running just updates ``last_seen`` on them.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.db import SessionLocal
from local_bazaar.scrapers.base import ProductPrice, upsert_prices

log = logging.getLogger("seed_test_db")

# (name, variety, category, unit, base_price) — base_price drifts by a small
# daily delta per city so charts have visible movement instead of flat lines.
_MOCK_PRODUCTS: list[tuple[str, str | None, str, str, Decimal]] = [
    ("Domates", "Salkım", "Geleneksel(Konvansiyonel)", "Kg", Decimal("18.50")),
    ("Salatalık", None, "Geleneksel(Konvansiyonel)", "Kg", Decimal("12.75")),
    ("Elma", "Starking", "Geleneksel(Konvansiyonel)", "Kg", Decimal("22.00")),
    ("Patates", None, "Geleneksel(Konvansiyonel)", "Kg", Decimal("9.25")),
]

_MOCK_CITIES = ["national", "istanbul"]
_LOOKBACK_DAYS = 7

# (province_slug, market_name, market_type, lat, lng) — coordinates are
# approximate central points, close enough for a mock map view.
_MOCK_MARKETS: list[tuple[str, str, str, float, float]] = [
    ("istanbul", "Salı Pazarı (Mock)", "semt_pazari", 41.0082, 28.9784),
    ("istanbul", "Kadıköy Üretici Pazarı (Mock)", "uretici_pazari", 40.9908, 29.0272),
    ("ankara", "Çarşamba Pazarı (Mock)", "semt_pazari", 39.9208, 32.8541),
    ("izmir", "Kemeraltı Pazarı (Mock)", "semt_pazari", 38.4192, 27.1287),
]


def _mock_prices(today: date) -> list[ProductPrice]:
    """Build a week of synthetic ``ProductPrice`` rows for the mock products.

    Returns:
        One record per (city, product, day) combination, with a small
        deterministic daily drift so charts show movement.
    """
    prices: list[ProductPrice] = []
    for city_slug in _MOCK_CITIES:
        city_name = "National" if city_slug == "national" else city_slug.capitalize()
        for name, variety, category, unit, base in _MOCK_PRODUCTS:
            for offset in range(_LOOKBACK_DAYS):
                day = today - timedelta(days=offset)
                # Deterministic drift: cents-level daily wobble, city-shifted
                # slightly so the two cities' lines aren't identical.
                drift = Decimal(offset % 4) * Decimal("0.15")
                city_shift = Decimal("0.50") if city_slug != "national" else Decimal("0")
                price = base + drift + city_shift
                prices.append(
                    ProductPrice(
                        city_name=city_name,
                        bulletin_date=day,
                        product_name=name,
                        product_variety=variety,
                        product_category=category,
                        average_price=price,
                        transaction_volume=1000 + offset * 25,
                        unit_name=unit,
                    )
                )
    return prices


async def _seed_markets(session: AsyncSession) -> int:
    """Insert a handful of geocoded mock markets, keyed by province slug.

    Looks up a real district under each requested province (seeded by
    migration 0002) so the mock rows satisfy the ``markets`` FK constraints
    without hardcoding a district slug that might not match the fixture.

    Args:
        session: An open async DB session.

    Returns:
        The number of markets inserted or refreshed.
    """
    written = 0
    for province_slug, name, market_type, lat, lng in _MOCK_MARKETS:
        district_id = (
            await session.execute(
                text(
                    """
                    SELECT d.id FROM districts d
                    JOIN provinces p ON p.id = d.province_id
                    WHERE p.slug = :province_slug
                    ORDER BY d.id
                    LIMIT 1
                    """
                ),
                {"province_slug": province_slug},
            )
        ).scalar()
        if district_id is None:
            log.warning(
                "No district found for province '%s' — did you run `alembic upgrade head`? "
                "Skipping market '%s'.",
                province_slug,
                name,
            )
            continue
        await session.execute(
            text(
                """
                INSERT INTO markets
                    (district_id, market_type, name, latitude, longitude,
                     geocoded_at, last_seen, created_at)
                VALUES (:did, :mtype, :name, :lat, :lng, now(), now(), now())
                ON CONFLICT (district_id, market_type, name)
                DO UPDATE SET latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
                              last_seen = now()
                """
            ),
            {"did": district_id, "mtype": market_type, "name": name, "lat": lat, "lng": lng},
        )
        written += 1
    await session.commit()
    return written


async def main() -> int:
    """Seed mock prices and markets into whatever ``DATABASE_URL`` points at.

    Returns:
        Exit code: 0 on success.
    """
    today = date.today()
    async with SessionLocal() as session:
        rows_written = await upsert_prices(session, _mock_prices(today))
        log.info("Seeded %d price rows across %s.", rows_written, ", ".join(_MOCK_CITIES))

        markets_written = await _seed_markets(session)
        log.info("Seeded %d mock markets.", markets_written)

    return 0


def cli() -> None:
    """Entry point used by ``python scripts/seed_test_db.py``."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if sys.platform == "win32":
        # psycopg's async driver can't run on Windows' default ProactorEventLoop.
        # Same workaround as migrations/env.py's _run_online().
        import selectors

        sys.exit(
            asyncio.run(
                main(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
            )
        )
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
