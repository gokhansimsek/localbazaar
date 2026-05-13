"""Server-side geocoding via the Google Maps Geocoding API.

The same API key is used by the JS map widget on the frontend, but the backend uses
it for batch geocoding so that map pins can be rendered without each browser making
its own geocoding request.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from local_bazaar.config import settings
from local_bazaar.models import District, Market, Province

log = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


@dataclass(slots=True)
class GeocodeResult:
    """Latitude / longitude pair returned by Google Geocoding."""

    latitude: float
    longitude: float


async def geocode_address(
    client: httpx.AsyncClient, query: str, api_key: str | None = None
) -> GeocodeResult | None:
    """Resolve a free-form address to latitude/longitude via Google Geocoding.

    Args:
        client: An open :class:`httpx.AsyncClient`.
        query: Free-form address string. Country bias to Turkey is applied automatically.
        api_key: Override the configured Google Maps API key. Defaults to
            :attr:`Settings.google_maps_api_key`.

    Returns:
        A :class:`GeocodeResult` on success; ``None`` when no result is found or the
        API key is missing.
    """
    key = api_key if api_key is not None else settings.google_maps_api_key
    if not key:
        log.debug("GOOGLE_MAPS_API_KEY is not set — skipping geocode for %r", query)
        return None

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    ):
        with attempt:
            resp = await client.get(
                GEOCODE_URL,
                params={
                    "address": query,
                    "components": "country:TR",
                    "language": "tr",
                    "key": key,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") != "OK" or not payload.get("results"):
                return None
            location = payload["results"][0]["geometry"]["location"]
            return GeocodeResult(latitude=location["lat"], longitude=location["lng"])
    return None  # pragma: no cover


async def geocode_pending_markets(session: AsyncSession, *, max_calls: int = 200) -> int:
    """Geocode every market that does not yet have lat/lng.

    Stops early after ``max_calls`` to stay within Google's daily quota.

    Args:
        session: An open async DB session.
        max_calls: Upper bound on the number of geocode API calls to issue per run.

    Returns:
        The number of markets successfully geocoded in this batch.
    """
    if not settings.google_maps_api_key:
        log.info("Geocoding skipped — GOOGLE_MAPS_API_KEY is empty.")
        return 0

    stmt = (
        select(Market, District, Province)
        .join(District, col(District.id) == col(Market.district_id))
        .join(Province, col(Province.id) == col(District.province_id))
        .where(col(Market.latitude).is_(None))
        .limit(max_calls)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return 0

    written = 0
    async with httpx.AsyncClient(
        timeout=15.0, headers={"User-Agent": settings.scraper_user_agent}
    ) as client:
        for market, district, province in rows:
            address_parts = [market.address, district.name, province.name, "Türkiye"]
            query = ", ".join(p for p in address_parts if p)
            result = await geocode_address(client, query)
            if result is not None:
                market.latitude = result.latitude
                market.longitude = result.longitude
                market.geocoded_at = datetime.now(UTC)
                written += 1
            # Google free tier: 50 QPS; be conservative.
            await asyncio.sleep(0.05)

    await session.commit()
    log.info("Geocoded %d markets (queried %d).", written, len(rows))
    return written
