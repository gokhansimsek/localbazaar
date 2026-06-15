"""Read-only API for the markets / map view.

Endpoints:
- ``GET /provinces``                            — list provinces with district counts.
- ``GET /provinces/{slug}/districts``           — list districts within a province.
- ``GET /markets?province=&district=&type=``    — list markets (with lat/lng) for the map.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from local_bazaar.db import get_session
from local_bazaar.models import District, Market, MarketType, Province

router = APIRouter()


class ProvinceOut(BaseModel):
    """Public projection of a row in the ``provinces`` table."""

    slug: str
    name: str
    plate_code: int | None


class DistrictOut(BaseModel):
    """Public projection of a row in the ``districts`` table."""

    slug: str
    name: str
    province_slug: str


class MarketOut(BaseModel):
    """Public projection of a market — used by the map page."""

    id: int
    name: str
    market_type: str
    address: str | None
    day_of_week: str | None
    latitude: float | None
    longitude: float | None
    province: str
    district: str


@router.get("/provinces", response_model=list[ProvinceOut])
async def list_provinces(session: AsyncSession = Depends(get_session)) -> list[ProvinceOut]:
    """List every province, alphabetically by name.

    Args:
        session: Injected DB session.

    Returns:
        Every row from the ``provinces`` table.
    """
    rows = (await session.execute(select(Province).order_by(col(Province.name)))).scalars().all()
    return [ProvinceOut(slug=p.slug, name=p.name, plate_code=p.plate_code) for p in rows]


@router.get("/provinces/{slug}/districts", response_model=list[DistrictOut])
async def list_districts(
    slug: str, session: AsyncSession = Depends(get_session)
) -> list[DistrictOut]:
    """List the districts that belong to a province.

    Args:
        slug: Province slug.
        session: Injected DB session.

    Returns:
        Districts ordered alphabetically by name.

    Raises:
        HTTPException: 404 if ``slug`` is not a known province.
    """
    province = (
        await session.execute(select(Province).where(col(Province.slug) == slug))
    ).scalar_one_or_none()
    if province is None:
        raise HTTPException(status_code=404, detail=f"Province '{slug}' not found")
    rows = (
        (
            await session.execute(
                select(District)
                .where(col(District.province_id) == province.id)
                .order_by(col(District.name))
            )
        )
        .scalars()
        .all()
    )
    return [DistrictOut(slug=d.slug, name=d.name, province_slug=province.slug) for d in rows]


_DAY_NAMES = {
    "Pazartesi",
    "Salı",
    "Çarşamba",
    "Perşembe",
    "Cuma",
    "Cumartesi",
    "Pazar",
}


@router.get("/markets", response_model=list[MarketOut])
async def list_markets(
    province: str | None = Query(default=None, description="Province slug filter."),
    district: str | None = Query(default=None, description="District slug filter."),
    market_type: MarketType | None = Query(default=None, alias="type"),
    day: str | None = Query(
        default=None,
        description="Filter by a single Turkish day name (Pazartesi/Salı/.../Pazar).",
    ),
    only_geocoded: bool = Query(default=False, alias="geocoded"),
    session: AsyncSession = Depends(get_session),
) -> list[MarketOut]:
    """List markets, optionally filtered by province / district / type / day.

    Args:
        province: Province slug filter; ``None`` means no province filter.
        district: District slug filter; ``None`` means no district filter.
        market_type: Filter by market type; ``None`` means all types.
        day: A single full Turkish day name (e.g. ``"Pazartesi"``). Matched
            against the comma-separated ``day_of_week`` field as an exact
            token, so ``"Pazar"`` does not match ``"Pazartesi"``.
        only_geocoded: When true, exclude markets without lat/lng.
        session: Injected DB session.

    Returns:
        Matching markets enriched with province and district names.

    Raises:
        HTTPException: 400 if ``day`` is not a recognized Turkish day name.
    """
    stmt = (
        select(Market, District, Province)
        .join(District, col(District.id) == col(Market.district_id))
        .join(Province, col(Province.id) == col(District.province_id))
    )
    if province is not None:
        stmt = stmt.where(col(Province.slug) == province)
    if district is not None:
        stmt = stmt.where(col(District.slug) == district)
    if market_type is not None:
        stmt = stmt.where(col(Market.market_type) == market_type)
    if day is not None:
        if day not in _DAY_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown day '{day}'. Expected one of: {sorted(_DAY_NAMES)}.",
            )
        # Comma-split exact match so "Pazar" won't catch "Pazartesi".
        # Cast the bound array to text[] so it matches string_to_array's text[]
        # output; without the cast psycopg binds it as varchar[] and Postgres
        # has no `text[] @> varchar[]` operator (raises UndefinedFunction).
        stmt = stmt.where(
            text("string_to_array(day_of_week, ',') @> ARRAY[:day]::text[]").bindparams(day=day)
        )
    if only_geocoded:
        stmt = stmt.where(col(Market.latitude).is_not(None))

    stmt = stmt.order_by(col(Province.name), col(District.name), col(Market.name))
    rows = (await session.execute(stmt)).all()

    return [
        MarketOut(
            id=market.id or 0,
            name=market.name,
            market_type=str(market.market_type),
            address=market.address,
            day_of_week=market.day_of_week,
            latitude=market.latitude,
            longitude=market.longitude,
            province=province_row.name,
            district=district_row.name,
        )
        for market, district_row, province_row in rows
    ]
