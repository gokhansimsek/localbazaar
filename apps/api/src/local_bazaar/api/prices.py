"""Read-only API for the Next.js UI.

Endpoints:
- ``GET /cities``                                    — list enabled cities
- ``GET /cities/{slug}/prices?date=YYYY-MM-DD``      — daily bulletin for a city
- ``GET /products/{name}/history?city=&from=&to=``   — price time series for a product
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import bindparam as sa_bindparam
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from local_bazaar.db import get_session, prices_table_name
from local_bazaar.models import City

Granularity = Literal["daily", "weekly", "monthly"]

# Maps each granularity to the PostgreSQL ``date_trunc`` unit. ``daily`` does
# not aggregate, so it never appears here.
_TRUNC_UNIT: dict[Granularity, str] = {
    "weekly": "week",
    "monthly": "month",
}

router = APIRouter()


async def _existing_slugs(session: AsyncSession, slugs: list[str]) -> list[str]:
    """Filter ``slugs`` down to those whose ``prices_<slug>`` table exists.

    Newly-seeded cities and cities with placeholder scrapers never trigger
    :func:`local_bazaar.db.ensure_city_table` until the first real row is
    written, so a UNION ALL across every registered slug would fail with
    ``UndefinedTable``. This helper preserves the input order.

    Args:
        session: An open async DB session.
        slugs: Candidate city slugs to check.

    Returns:
        The subset of ``slugs`` whose backing table is present in the DB.
    """
    if not slugs:
        return []
    table_names = [prices_table_name(s) for s in slugs]
    # ``expanding=True`` makes SQLAlchemy emit per-element bind params, which
    # works with ``IN (...)`` but breaks ``ANY(:array)``. Use ``IN`` here.
    result = await session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name IN :names"
        ).bindparams(sa_bindparam("names", value=table_names, expanding=True))
    )
    present = {row[0] for row in result.all()}
    return [s for s in slugs if prices_table_name(s) in present]


# --- Response schemas ------------------------------------------------------


class CityOut(BaseModel):
    """Public projection of a row in the ``cities`` registry."""

    slug: str
    name: str
    source_type: str
    enabled: bool


class PriceRow(BaseModel):
    """One row of the daily bulletin for a single city."""

    bulletin_date: date
    product_name: str
    product_variety: str | None
    product_category: str | None
    average_price: Decimal
    transaction_volume: int | None
    unit_name: str


class HistoryPoint(BaseModel):
    """One point on a product's historical price series, tagged by city and variant.

    ``product_variety`` and ``product_category`` are kept on the wire so the
    frontend can split distinct production methods into their own chart series
    instead of accidentally collapsing them.
    """

    bulletin_date: date
    city_slug: str
    product_variety: str | None
    product_category: str | None
    average_price: Decimal
    unit_name: str


class ProductOut(BaseModel):
    """Distinct product surfaced for the trends picker."""

    product_name: str
    unit_name: str
    latest_bulletin_date: date
    latest_average_price: Decimal


# --- Endpoints -------------------------------------------------------------


@router.get("/cities", response_model=list[CityOut])
async def list_cities(session: AsyncSession = Depends(get_session)) -> list[CityOut]:
    """List every enabled city in alphabetical order by display name.

    Args:
        session: Injected DB session.

    Returns:
        All enabled cities; disabled cities are filtered out.
    """
    result = await session.execute(
        select(City).where(col(City.enabled).is_(True)).order_by(col(City.name))
    )
    return [
        CityOut(
            slug=c.slug,
            name=c.name,
            source_type=str(c.source_type),
            enabled=c.enabled,
        )
        for c in result.scalars().all()
    ]


@router.get("/cities/{slug}/prices", response_model=list[PriceRow])
async def city_prices(
    slug: str,
    bulletin_date: date | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> list[PriceRow]:
    """Return the daily bulletin rows for a single city.

    Args:
        slug: City slug as known to the ``cities`` registry.
        bulletin_date: Bulletin date to fetch; defaults to the latest available date
            for the city when omitted.
        session: Injected DB session.

    Returns:
        Rows from ``prices_<slug>`` for the requested (or latest) bulletin date.

    Raises:
        HTTPException: 404 if ``slug`` is not registered or disabled.
    """
    city = (
        await session.execute(
            select(City).where(col(City.slug) == slug, col(City.enabled).is_(True))
        )
    ).scalar_one_or_none()
    if city is None:
        raise HTTPException(status_code=404, detail=f"City '{slug}' not registered")

    table_name = prices_table_name(slug)
    # ``to_regclass`` returns NULL when the table does not exist. Newly-seeded
    # cities (or placeholder scrapers that have never written) won't have a
    # ``prices_<slug>`` table yet, so treat that as "no data" rather than 500.
    exists = (
        await session.execute(text("SELECT to_regclass(:n)"), {"n": table_name})
    ).scalar()
    if exists is None:
        return []

    if bulletin_date is None:
        latest = await session.execute(
            text(f"SELECT MAX(bulletin_date) FROM {table_name}")
        )
        bulletin_date = latest.scalar()
        if bulletin_date is None:
            return []

    # Phase 3 schema: textual product fields come from the products registry
    # via a JOIN on product_id. The wire format is unchanged.
    rows = (
        await session.execute(
            text(
                f"""
                SELECT pn.bulletin_date,
                       p.name AS product_name,
                       p.variety AS product_variety,
                       p.category AS product_category,
                       pn.average_price,
                       pn.transaction_volume,
                       p.unit_name
                FROM {table_name} pn
                JOIN products p ON p.id = pn.product_id
                WHERE pn.bulletin_date = :d
                ORDER BY p.name, p.variety, p.category
                """
            ),
            {"d": bulletin_date},
        )
    ).mappings().all()
    return [PriceRow(**row) for row in rows]


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    city: str | None = Query(default=None, description="Restrict to one city; default unions all."),
    session: AsyncSession = Depends(get_session),
) -> list[ProductOut]:
    """List every distinct product across the registered cities, alphabetically.

    Each item carries the most recent bulletin date and price seen for that
    product so the picker can show a quick preview without a second round-trip.

    Args:
        city: Optional city slug filter; ``None`` (default) unions every enabled city.
        session: Injected DB session.

    Returns:
        Distinct products sorted by ``product_name``.
    """
    cities_stmt = select(col(City.slug)).where(col(City.enabled).is_(True))
    if city is not None:
        cities_stmt = cities_stmt.where(col(City.slug) == city)
    slugs = list((await session.execute(cities_stmt)).scalars().all())
    slugs = await _existing_slugs(session, slugs)
    if not slugs:
        return []

    # Phase 3: textual fields come from the products registry. We UNION ALL
    # the (product_id, date, price) tuples across the requested cities, JOIN
    # each to products, then keep the latest row per product name.
    union_sql = "\nUNION ALL\n".join(
        f"SELECT product_id, bulletin_date, average_price FROM {prices_table_name(s)}"
        for s in slugs
    )
    sql = f"""
        SELECT DISTINCT ON (p.name)
            p.name AS product_name,
            p.unit_name,
            src.bulletin_date,
            src.average_price
        FROM ({union_sql}) src
        JOIN products p ON p.id = src.product_id
        ORDER BY p.name, src.bulletin_date DESC
    """
    rows = (await session.execute(text(sql))).mappings().all()
    return [
        ProductOut(
            product_name=r["product_name"],
            unit_name=r["unit_name"],
            latest_bulletin_date=r["bulletin_date"],
            latest_average_price=r["average_price"],
        )
        for r in rows
    ]


@router.get("/products/{name}/history", response_model=list[HistoryPoint])
async def product_history(
    name: str,
    city: str | None = Query(default=None, description="If omitted, returns all cities."),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    granularity: Granularity = Query(
        default="daily",
        description=(
            "Aggregation level. ``daily`` returns raw bulletin rows. ``weekly`` and "
            "``monthly`` bucket by ISO week / calendar month and return the mean "
            "``average_price`` per (city × category × variety × bucket). The "
            "``bulletin_date`` field carries the bucket start (Monday for weekly, "
            "first of month for monthly)."
        ),
    ),
    session: AsyncSession = Depends(get_session),
) -> list[HistoryPoint]:
    """Return the historical price series for a product across one or all cities.

    Args:
        name: Product name as stored in the bulletin (case-sensitive, Turkish).
        city: Optional city slug filter; when omitted, the UNION ALL covers every
            enabled city.
        date_from: Inclusive lower bound on ``bulletin_date``; ``None`` means no lower bound.
        date_to: Inclusive upper bound on ``bulletin_date``; ``None`` means no upper bound.
        granularity: ``"daily"`` (default), ``"weekly"``, or ``"monthly"``. The
            two latter values do server-side aggregation via PostgreSQL
            ``date_trunc`` + ``AVG`` so the wire payload shrinks dramatically
            for long ranges.
        session: Injected DB session.

    Returns:
        Time-series points sorted by date then city slug. Empty when no city is
        registered or no rows match the filters.
    """
    cities_stmt = select(col(City.slug)).where(col(City.enabled).is_(True))
    if city is not None:
        cities_stmt = cities_stmt.where(col(City.slug) == city)
    slugs = list((await session.execute(cities_stmt)).scalars().all())
    slugs = await _existing_slugs(session, slugs)
    if not slugs:
        return []

    date_clauses: list[str] = []
    params: dict[str, object] = {"name": name}
    if date_from is not None:
        date_clauses.append("pn.bulletin_date >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        date_clauses.append("pn.bulletin_date <= :date_to")
        params["date_to"] = date_to
    date_where = (" AND " + " AND ".join(date_clauses)) if date_clauses else ""

    if granularity == "daily":
        # Phase 3: every per-city UNION arm joins prices_<slug> with products
        # on product_id, filtering by the canonical product name.
        union_sql = "\nUNION ALL\n".join(
            f"SELECT '{s}'::text AS city_slug, pn.bulletin_date, "
            f"p.variety AS product_variety, p.category AS product_category, "
            f"pn.average_price, p.unit_name "
            f"FROM {prices_table_name(s)} pn "
            f"JOIN products p ON p.id = pn.product_id "
            f"WHERE p.name = :name{date_where}"
            for s in slugs
        )
    else:
        unit = _TRUNC_UNIT[granularity]
        # Bucket per (city, week|month, variety, category). AVG cast back to
        # numeric(12,4) preserves wire precision.
        union_sql = "\nUNION ALL\n".join(
            f"SELECT '{s}'::text AS city_slug, "
            f"date_trunc('{unit}', pn.bulletin_date)::date AS bulletin_date, "
            f"p.variety AS product_variety, p.category AS product_category, "
            f"AVG(pn.average_price)::numeric(12,4) AS average_price, "
            f"MAX(p.unit_name) AS unit_name "
            f"FROM {prices_table_name(s)} pn "
            f"JOIN products p ON p.id = pn.product_id "
            f"WHERE p.name = :name{date_where} "
            f"GROUP BY date_trunc('{unit}', pn.bulletin_date), p.variety, p.category"
            for s in slugs
        )

    sql = f"{union_sql}\nORDER BY bulletin_date, city_slug, product_category, product_variety"
    rows = (await session.execute(text(sql), params)).mappings().all()
    return [HistoryPoint(**row) for row in rows]
