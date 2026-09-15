"""Shared scraper contract.

Every concrete scraper exposes ``async run(session) -> int`` and emits ``ProductPrice``
records. The base helper here turns those records into idempotent UPSERTs against the
right ``prices_<slug>`` table.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

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
from local_bazaar.products_normalize import (
    is_fish_name,
    normalize,
    normalize_category,
    normalize_unit,
    promote_category_words,
)

log = logging.getLogger(__name__)


class RobotsDisallowedError(Exception):
    """Raised when ``robots.txt`` explicitly disallows fetching a URL.

    This is intentionally distinct from ``httpx`` exceptions so that
    :func:`fetch_with_retry`'s ``tenacity`` retry policy never mistakes a
    robots.txt refusal for a transient network failure, and so callers can
    catch it specifically to treat the scrape as "no data for this run"
    instead of a hard failure.
    """

    def __init__(self, url: str, user_agent: str) -> None:
        """Build the exception.

        Args:
            url: The URL ``robots.txt`` disallows fetching.
            user_agent: The user-agent string the disallow was evaluated
                against.
        """
        # Pass both positional args through to Exception.__init__ (rather than
        # a pre-formatted string) so pickling/copying round-trips correctly;
        # __str__ below renders the human-readable message.
        super().__init__(url, user_agent)
        self.url = url
        self.user_agent = user_agent

    def __str__(self) -> str:
        """Render a human-readable message for logs and tracebacks.

        Returns:
            A one-line description naming the disallowed URL and user agent.
        """
        return f"robots.txt disallows {self.url!r} for user-agent {self.user_agent!r}"


# Per-origin (``scheme://host[:port]``) cache of parsed robots.txt rules. No
# TTL: each scraper process is short-lived (a scheduled run finishes and
# exits, or the in-process scheduler fires once a day), so re-fetching
# robots.txt more than once per process would only add pointless traffic.
_robots_cache: dict[str, RobotFileParser] = {}
_robots_locks: dict[str, asyncio.Lock] = {}


def _robots_lock(origin: str) -> asyncio.Lock:
    """Return (creating on first use) the lock guarding one origin's robots.txt fetch.

    Args:
        origin: ``scheme://host[:port]`` cache key.

    Returns:
        The :class:`asyncio.Lock` serializing concurrent first-fetches for
        ``origin`` so two coroutines never race to populate the cache.
    """
    lock = _robots_locks.get(origin)
    if lock is None:
        lock = asyncio.Lock()
        _robots_locks[origin] = lock
    return lock


async def _fetch_robots_txt(origin: str) -> str | None:
    """Best-effort fetch of ``<origin>/robots.txt``.

    Uses its own short-lived client rather than :func:`fetch_with_retry` —
    robots.txt fetches are exempt from robots.txt checks by convention, and
    routing through :func:`fetch_with_retry` here would recurse.

    Args:
        origin: ``scheme://host[:port]`` to fetch ``robots.txt`` from.

    Returns:
        The response body as text, or ``None`` if it could not be fetched
        cleanly (network error, timeout, or any non-2xx status including a
        404 — a missing robots.txt conventionally means "no restrictions").
    """
    url = f"{origin}/robots.txt"
    try:
        async with http_client(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        log.info("robots.txt fetch failed for %s (%s) — failing open.", origin, exc)
        return None
    if resp.status_code != 200:
        log.info(
            "robots.txt fetch for %s returned HTTP %d — failing open.",
            origin,
            resp.status_code,
        )
        return None
    return resp.text


async def _get_robot_parser(origin: str) -> RobotFileParser:
    """Return the cached (or freshly fetched) :class:`RobotFileParser` for ``origin``.

    Args:
        origin: ``scheme://host[:port]`` cache key.

    Returns:
        A parser that has always had :meth:`~RobotFileParser.parse` called at
        least once. Note ``RobotFileParser.can_fetch()`` returns ``False``
        (fail *closed*) until ``parse()``/``read()`` has run — so an
        unreachable or malformed robots.txt is parsed as an empty rule set
        (``parser.parse([])``) rather than left untouched, which makes
        ``can_fetch()`` correctly fail *open* (no rules == allow everything)
        instead of silently blocking every scrape.
    """
    cached = _robots_cache.get(origin)
    if cached is not None:
        return cached
    async with _robots_lock(origin):
        # Another coroutine may have populated the cache while we waited.
        cached = _robots_cache.get(origin)
        if cached is not None:
            return cached
        content = await _fetch_robots_txt(origin)
        parser = RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        # Parsing is synchronous, but robots.txt files are tiny (a few KB at
        # most) — the network fetch above is the only part that can be slow,
        # and that one is fully async.
        parser.parse(content.splitlines() if content is not None else [])
        _robots_cache[origin] = parser
        return parser


async def is_allowed(url: str, user_agent: str | None = None) -> bool:
    """Check whether ``url`` may be fetched according to its site's ``robots.txt``.

    Fetches and caches each site's ``robots.txt`` (keyed by scheme+host) the
    first time a URL on that host is checked, so repeated checks against the
    same site cost nothing beyond a dict lookup.

    Args:
        url: Absolute URL the caller wants to fetch.
        user_agent: User-agent string to evaluate the rules against. Defaults
            to :data:`local_bazaar.config.settings.scraper_user_agent` — the
            same UA the scraper actually sends on the wire.

    Returns:
        ``True`` if the fetch is allowed — including when ``robots.txt``
        itself could not be fetched or parsed, which fails open rather than
        blocking every scrape. ``False`` only when an explicit ``Disallow``
        rule matches ``url``.
    """
    agent = user_agent or settings.scraper_user_agent
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = await _get_robot_parser(origin)
    return parser.can_fetch(agent, url)


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
        RobotsDisallowedError: If ``robots.txt`` explicitly disallows ``url``
            for :data:`local_bazaar.config.settings.scraper_user_agent`.
        httpx.HTTPStatusError: If the final response has a non-2xx status.
        httpx.TimeoutException: If retries are exhausted on timeouts.
    """
    if not await is_allowed(url):
        raise RobotsDisallowedError(url, settings.scraper_user_agent)
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
    category = normalize_category(raw_category)
    name, variety, category = promote_category_words(name, variety, category)
    unit = normalize_unit(raw_unit)
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
            # Drop fish/seafood centrally — the platform scope is produce only.
            # The national scraper filters at source; this catches per-city
            # sources (e.g. Bursa's seafood tab) that emit fish rows.
            if is_fish_name(p.product_name):
                continue
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
