"""Shared scraper contract.

Every concrete scraper exposes ``async run(session) -> int`` and emits ``ProductPrice``
records. The base helper here turns those records into idempotent UPSERTs against the
right ``prices_<slug>`` table.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from local_bazaar.config import settings
from local_bazaar.db import city_slug, ensure_city_table, prices_table_name

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ProductPrice:
    """One product-price record emitted by a scraper before it lands in the DB."""

    city_name: str
    bulletin_date: date
    product_name: str
    product_variety: str | None
    product_category: str | None
    average_price: Decimal
    transaction_volume: int | None
    unit_name: str


def http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Build an :class:`httpx.AsyncClient` configured with the project User-Agent.

    Args:
        timeout: Total request timeout in seconds.

    Returns:
        An async HTTP client ready to use inside ``async with``.
    """
    return httpx.AsyncClient(
        headers={"User-Agent": settings.scraper_user_agent},
        timeout=timeout,
        follow_redirects=True,
    )


async def fetch_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request and retry on transient network failures.

    Args:
        client: An open :class:`httpx.AsyncClient`.
        method: HTTP verb (``"GET"``, ``"POST"`` …).
        url: Absolute URL to request.
        **kwargs: Forwarded to :meth:`httpx.AsyncClient.request`.

    Returns:
        The successful :class:`httpx.Response`. Raises on 4xx/5xx without retry.

    Raises:
        httpx.HTTPStatusError: If the final response has a non-2xx status.
        httpx.TimeoutException: If retries are exhausted on timeouts.
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    ):
        with attempt:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
    raise RuntimeError("unreachable")  # pragma: no cover


async def upsert_prices(
    session: AsyncSession,
    prices: Iterable[ProductPrice] | AsyncIterable[ProductPrice],
) -> int:
    """Group prices by city slug, ensure each city's table exists, and UPSERT every row.

    Args:
        session: An open async DB session. The function calls ``commit()`` itself.
        prices: A synchronous or asynchronous iterable of :class:`ProductPrice` records.

    Returns:
        The total number of rows written across all per-city tables.
    """
    by_slug: dict[str, list[ProductPrice]] = {}

    if hasattr(prices, "__aiter__"):
        async for p in prices:  # type: ignore[union-attr]
            by_slug.setdefault(city_slug(p.city_name), []).append(p)
    else:
        for p in prices:  # type: ignore[assignment]
            by_slug.setdefault(city_slug(p.city_name), []).append(p)

    written = 0
    for slug, items in by_slug.items():
        await ensure_city_table(session, slug)
        table_name = prices_table_name(slug)
        # ON CONFLICT mirrors the unique constraint defined in db.prices_table().
        stmt = text(
            f"""
            INSERT INTO {table_name}
                (bulletin_date, product_name, product_variety, product_category,
                 average_price, transaction_volume, unit_name, last_updated)
            VALUES
                (:bulletin_date, :product_name, :product_variety, :product_category,
                 :average_price, :transaction_volume, :unit_name, NOW())
            ON CONFLICT (bulletin_date, product_name, product_variety, product_category, unit_name)
            DO UPDATE SET
                average_price = EXCLUDED.average_price,
                transaction_volume = EXCLUDED.transaction_volume,
                last_updated = NOW()
            """
        )
        for p in items:
            await session.execute(
                stmt,
                {
                    "bulletin_date": p.bulletin_date,
                    "product_name": p.product_name,
                    "product_variety": p.product_variety,
                    "product_category": p.product_category,
                    "average_price": p.average_price,
                    "transaction_volume": p.transaction_volume,
                    "unit_name": p.unit_name,
                },
            )
            written += 1

    await session.commit()
    return written
