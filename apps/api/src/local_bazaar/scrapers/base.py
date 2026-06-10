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
from local_bazaar.products_normalize import normalize

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


async def _resolve_product_id(
    session: AsyncSession,
    raw_name: str,
    raw_variety: str | None,
    raw_category: str | None,
    raw_unit: str,
) -> int:
    """Find (or create) the ``products.id`` for one raw scraper tuple.

    The scraper emits source-shaped values
    (``product_name`` / ``product_variety`` / ``product_category`` /
    ``unit_name``). We feed those through
    :func:`local_bazaar.products_normalize.normalize` to get the canonical
    name + variety, then look up the matching row in ``products``. New tuples
    are inserted on the fly so the daily scrape never blocks on a missing
    product row.

    Args:
        session: An open async DB session.
        raw_name: Source ``product_name`` (any case).
        raw_variety: Source ``product_variety`` (any case, or ``None``).
        raw_category: Source ``product_category``, kept verbatim.
        raw_unit: Source ``unit_name`` (``Kg`` / ``Adet`` / ``Pk/125 G`` …).

    Returns:
        The ``products.id`` for the normalized tuple.
    """
    name, variety = normalize(raw_name, raw_variety)
    category = (raw_category or "").strip() or None
    unit = raw_unit.strip()
    res = await session.execute(
        text(
            """
            SELECT id FROM products
            WHERE name = :name
              AND COALESCE(variety, '') = COALESCE(:variety, '')
              AND COALESCE(category, '') = COALESCE(:category, '')
              AND unit_name = :unit
            LIMIT 1
            """
        ),
        {"name": name, "variety": variety, "category": category, "unit": unit},
    )
    pid = res.scalar()
    if pid is not None:
        return int(pid)
    res = await session.execute(
        text(
            """
            INSERT INTO products (name, variety, category, unit_name)
            VALUES (:name, :variety, :category, :unit)
            ON CONFLICT (name, COALESCE(variety, ''), COALESCE(category, ''), unit_name)
            DO UPDATE SET unit_name = EXCLUDED.unit_name
            RETURNING id
            """
        ),
        {"name": name, "variety": variety, "category": category, "unit": unit},
    )
    new_id = res.scalar()
    assert new_id is not None
    return int(new_id)


async def upsert_prices(
    session: AsyncSession,
    prices: Iterable[ProductPrice] | AsyncIterable[ProductPrice],
) -> int:
    """Group prices by city slug, resolve each row to a ``product_id``, and UPSERT.

    Scrapers continue to emit raw (name, variety, category, unit) tuples. This
    function turns each unique tuple into a ``products.id`` (re-using one per
    batch via an in-memory cache), then writes ``prices_<slug>`` rows that
    reference the product registry. Per-row conflicts are resolved on the
    ``(bulletin_date, product_id)`` unique constraint defined by
    :func:`local_bazaar.db.prices_table`.

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
        stmt = text(
            f"""
            INSERT INTO {table_name}
                (bulletin_date, product_id, average_price, transaction_volume, last_updated)
            VALUES
                (:bulletin_date, :product_id, :average_price, :transaction_volume, NOW())
            ON CONFLICT (bulletin_date, product_id)
            DO UPDATE SET
                average_price = EXCLUDED.average_price,
                transaction_volume = EXCLUDED.transaction_volume,
                last_updated = NOW()
            """
        )
        # Cache (raw_name, raw_variety, raw_category, raw_unit) → product_id
        # within this batch so a 200-row bulletin only resolves once per
        # distinct product.
        pid_cache: dict[tuple[str, str, str, str], int] = {}
        for p in items:
            key = (
                p.product_name,
                p.product_variety or "",
                p.product_category or "",
                p.unit_name,
            )
            pid = pid_cache.get(key)
            if pid is None:
                pid = await _resolve_product_id(
                    session,
                    p.product_name,
                    p.product_variety,
                    p.product_category,
                    p.unit_name,
                )
                pid_cache[key] = pid
            await session.execute(
                stmt,
                {
                    "bulletin_date": p.bulletin_date,
                    "product_id": pid,
                    "average_price": p.average_price,
                    "transaction_volume": p.transaction_volume,
                },
            )
            written += 1

    await session.commit()
    return written
