"""Scraper for Ankara hal prices published at ankara.bel.tr.

The Ankara Büyükşehir Belediyesi publishes daily wholesale-market (hal) prices
for four product types — Meyve, Sebze, İthal, Balık — at
``https://www.ankara.bel.tr/hal-fiyatlari``. The page is a Laravel-style PHP
app (not ASP.NET WebForms like hal.gov.tr): it requires a session cookie plus
a CSRF token harvested from the initial GET, and the search form is submitted
as a normal ``application/x-www-form-urlencoded`` POST with ``date``
(``dd.mm.yyyy``) + ``type`` (``fruit`` / ``vegetable`` / ``imported`` / ``fish``).

Each run backfills the last ``lookback_days`` (default 160) days of Ankara
prices. For every day in that window:

1. Skip if ``prices_ankara`` already has at least one row for that date.
2. Otherwise POST the form once per product type, parse the result table,
   and UPSERT every row.

Notes about the page:
- No pagination — the result table for one (date, type) pair is a single,
  self-contained ``<table class="table table-custom ...">`` with columns
  ``Ürün Adı | Ürün Türü | Birim | En Düşük Fiyat (₺) | En Yüksek Fiyat (₺) | Tarih``.
- Each row carries the bulletin date in its last cell. We trust that value
  (the source falls back to the most recent business day when the requested
  date has no bulletin, so the rendered ``Tarih`` cell — not the requested
  date — is authoritative).
- Two prices per row (min / max). We persist the midpoint as
  ``average_price`` (no "average" is published).
- There is no "category" column (no Geleneksel / Organik split), so
  ``product_category`` is ``None`` on every row.
- Product names often embed the variety in parentheses, e.g.
  ``"Armut (Deveci)"`` or ``"Elma (Golden)"``. We split that out into
  ``product_variety`` so the schema stays consistent with hal.gov.tr.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.scrapers.base import (
    ProductPrice,
    fetch_with_retry,
    http_client,
    upsert_prices,
)

log = logging.getLogger(__name__)

URL = "https://www.ankara.bel.tr/hal-fiyatlari"
ANKARA_CITY_NAME = "Ankara"

# Internal value (form ``type``) → display label (``Ürün Türü`` column).
# We submit one POST per type per day. ``fish`` is intentionally NOT fetched
# (Meyve/Sebze platform only); ``imported`` IS kept because imported produce
# is still in scope.
PRODUCT_TYPES: tuple[tuple[str, str], ...] = (
    ("fruit", "Meyve"),
    ("vegetable", "Sebze"),
    ("imported", "İthal"),
)

# Default lookback window. Every scheduled run ensures the last `lookback_days`
# of bulletins are present in `prices_ankara` and re-scrapes the gaps.
_DEFAULT_LOOKBACK_DAYS = 160

# Two consecutive failed bulletin dates trigger an early break — typical when
# we walk past the start of the published history.
_MAX_CONSECUTIVE_EMPTY_DAYS = 14


class AnkaraScraper:
    """Scraper for the daily wholesale-market bulletin at ankara.bel.tr."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        request_sleep: float = 0.4,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill. Days
                that already have at least one row in ``prices_ankara`` are
                skipped without an HTTP request.
            request_sleep: Seconds to wait between successive POSTs so we
                don't hammer ankara.bel.tr.
        """
        self.lookback_days = lookback_days
        self.request_sleep = request_sleep

    async def run(self, session: AsyncSession) -> int:
        """Backfill every missing day in the last ``lookback_days``.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across all newly-scraped days. ``0`` is a
            valid return — it means every day in the lookback window already
            has data (or the source has none to give for those gaps).
        """
        today = _today_istanbul()
        total = 0
        consecutive_empty = 0
        async with http_client() as client:
            csrf_token = await self._bootstrap(client)
            if csrf_token is None:
                log.warning(
                    "ankara.bel.tr: could not extract CSRF token — aborting run."
                )
                return 0

            for offset in range(self.lookback_days):
                target = today - timedelta(days=offset)
                if await _has_data_for_date(session, target):
                    consecutive_empty = 0
                    continue
                wrote = await self._scrape_one_day(session, client, csrf_token, target)
                total += wrote
                if wrote == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= _MAX_CONSECUTIVE_EMPTY_DAYS:
                        log.info(
                            "ankara.bel.tr: %d consecutive empty days, "
                            "stopping backfill at %s.",
                            consecutive_empty,
                            target,
                        )
                        break
                else:
                    consecutive_empty = 0
        return total

    async def _scrape_one_day(
        self,
        session: AsyncSession,
        client: httpx.AsyncClient,
        csrf_token: str,
        target: date,
    ) -> int:
        """Fetch one day's bulletin (all four types) and UPSERT it.

        Args:
            session: An open async DB session.
            client: The shared httpx client (cookie jar carries PHPSESSID).
            csrf_token: The ``_token`` value harvested from the initial GET.
            target: The bulletin date to request.

        Returns:
            Number of rows written for that date (>= 0). Duplicates produced
            by the source's "fall back to most recent business day" behaviour
            are absorbed by the UPSERT.
        """
        prices: list[ProductPrice] = []
        async for p in self.iter_prices(client, csrf_token, target):
            prices.append(p)
        if not prices:
            log.info("ankara.bel.tr: no rows for %s", target)
            return 0
        wrote = await upsert_prices(session, prices)
        log.info("ankara.bel.tr: %s wrote %d rows", target, wrote)
        return wrote

    # --- Core scrape loop --------------------------------------------------

    async def iter_prices(
        self,
        client: httpx.AsyncClient,
        csrf_token: str,
        target_date: date,
    ) -> AsyncIterator[ProductPrice]:
        """Stream :class:`ProductPrice` records for one bulletin date.

        Iterates the four product types (Meyve, Sebze, İthal, Balık) — one
        POST per type — and yields a record per parsed data row. Each row's
        ``bulletin_date`` is read from the row's own ``Tarih`` cell, which
        the source uses to communicate the actual bulletin date even when
        the request asked for a non-business day.

        Args:
            client: The shared httpx client.
            csrf_token: The ``_token`` value to echo back in every POST.
            target_date: The bulletin date requested.

        Yields:
            One :class:`ProductPrice` per parsed data row.
        """
        seen_keys: set[tuple[date, str, str | None, str | None, str]] = set()
        for type_value, type_label in PRODUCT_TYPES:
            html = await self._post_search(client, csrf_token, target_date, type_value)
            if html is None:
                continue
            rows = list(_parse_table(html))
            log.info(
                "ankara.bel.tr: requested=%s type=%s rows=%d",
                target_date,
                type_value,
                len(rows),
            )
            for row in rows:
                price = self._row_to_price(row, type_label, target_date)
                if price is None:
                    continue
                # The unique key mirrors the DB unique constraint.
                key = (
                    price.bulletin_date,
                    price.product_name,
                    price.product_variety,
                    price.product_category,
                    price.unit_name,
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                yield price
            await asyncio.sleep(self.request_sleep)

    # --- HTTP --------------------------------------------------------------

    async def _bootstrap(self, client: httpx.AsyncClient) -> str | None:
        """GET the landing page so the cookie jar gets ``PHPSESSID`` set.

        Args:
            client: The shared httpx client.

        Returns:
            The CSRF token read from the ``<meta name="csrf-token">`` tag,
            or ``None`` if the page layout changed and the token isn't
            discoverable.
        """
        try:
            resp = await fetch_with_retry(client, "GET", URL)
        except httpx.HTTPStatusError as exc:
            log.warning("ankara.bel.tr: initial GET failed: %s", exc)
            return None
        return _extract_csrf_token(resp.text)

    async def _post_search(
        self,
        client: httpx.AsyncClient,
        csrf_token: str,
        target_date: date,
        type_value: str,
    ) -> str | None:
        """Submit the search form for one ``(date, type)`` pair.

        Args:
            client: The shared httpx client.
            csrf_token: ``_token`` value to echo back.
            target_date: Requested bulletin date.
            type_value: One of ``fruit`` / ``vegetable`` / ``imported`` /
                ``fish``.

        Returns:
            The response HTML, or ``None`` if the POST failed.
        """
        data = {
            "_token": csrf_token,
            "date": target_date.strftime("%d.%m.%Y"),
            "type": type_value,
        }
        headers = {
            "Referer": URL,
            "Origin": "https://www.ankara.bel.tr",
            "X-CSRF-TOKEN": csrf_token,
        }
        try:
            resp = await fetch_with_retry(
                client, "POST", URL, data=data, headers=headers
            )
        except httpx.HTTPStatusError as exc:
            log.warning(
                "ankara.bel.tr: POST date=%s type=%s failed: %s",
                target_date,
                type_value,
                exc,
            )
            return None
        return resp.text

    # --- Row mapping -------------------------------------------------------

    @staticmethod
    def _row_to_price(
        row: dict[str, str],
        type_label: str,
        requested_date: date,
    ) -> ProductPrice | None:
        """Map a parsed table row to a :class:`ProductPrice`.

        Args:
            row: A dict produced by :func:`_parse_table` with keys
                ``product_name``, ``product_type``, ``unit_name``,
                ``min_price``, ``max_price``, ``bulletin_date``.
            type_label: The ``Ürün Türü`` label associated with the POST
                that produced this row (``Meyve`` / ``Sebze`` / ``İthal`` /
                ``Balık``). Used as a fallback when the table cell is blank.
            requested_date: Date passed to the POST — used only if the row
                has no parseable ``Tarih`` cell.

        Returns:
            A :class:`ProductPrice`, or ``None`` if the row has no usable
            price (both min and max missing).
        """
        bulletin_date = _parse_dmy(row["bulletin_date"]) or requested_date
        product_name, product_variety = _split_variety(row["product_name"])
        category = (row.get("product_type") or "").strip() or type_label or None
        unit_name = (row.get("unit_name") or "").strip() or "kg"
        min_price = _to_decimal(row.get("min_price", ""))
        max_price = _to_decimal(row.get("max_price", ""))

        avg = _midpoint(min_price, max_price)
        if avg is None:
            return None

        return ProductPrice(
            city_name=ANKARA_CITY_NAME,
            bulletin_date=bulletin_date,
            product_name=product_name,
            product_variety=product_variety,
            product_category=category,
            average_price=avg,
            transaction_volume=None,
            unit_name=unit_name,
        )


# --- Module-level helpers (pure, easily testable) --------------------------


def _extract_csrf_token(html: str) -> str | None:
    """Read the CSRF token out of the ``<meta name="csrf-token">`` tag.

    Args:
        html: The HTML body of the landing page.

    Returns:
        The token string, or ``None`` if the tag is missing.
    """
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    return m.group(1) if m else None


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract product rows from the result table.

    Args:
        html: Response HTML from a search POST.

    Returns:
        A list of dicts with the keys ``product_name``, ``product_type``,
        ``unit_name``, ``min_price``, ``max_price``, ``bulletin_date``.
        Empty when the bulletin is missing or the table couldn't be located.
    """
    tree = HTMLParser(html)
    # The result table is the only ``table.table-custom`` on the page.
    table = tree.css_first("table.table-custom")
    if table is None:
        # Fall back to any ``<table>`` whose first ``<th>`` is ``Ürün Adı``.
        for candidate in tree.css("table"):
            headers = [th.text(strip=True) for th in candidate.css("th")]
            if headers and headers[0].startswith("Ürün"):
                table = candidate
                break
    if table is None:
        return []

    rows: list[dict[str, str]] = []
    for tr in table.css("tbody tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 6:
            continue
        product_name = cells[0]
        if not product_name or not any(ch.isalpha() for ch in product_name):
            continue
        rows.append(
            {
                "product_name": product_name,
                "product_type": cells[1],
                "unit_name": cells[2],
                "min_price": cells[3],
                "max_price": cells[4],
                "bulletin_date": cells[5],
            }
        )
    return rows


def _split_variety(name: str) -> tuple[str, str | None]:
    """Split a product label like ``"Armut (Deveci)"`` into base + variety.

    Args:
        name: The raw ``Ürün Adı`` cell.

    Returns:
        ``(product_name, product_variety)``. ``product_variety`` is ``None``
        when the name has no trailing parenthetical.
    """
    cleaned = name.strip()
    m = re.match(r"^(.+?)\s*\(([^()]+)\)\s*$", cleaned)
    if not m:
        return cleaned, None
    base = m.group(1).strip()
    variety = m.group(2).strip()
    if not base:
        return cleaned, None
    return base, variety or None


def _parse_dmy(value: str) -> date | None:
    """Parse a ``dd.mm.yyyy`` string into a :class:`date`, tolerating noise.

    Args:
        value: Raw cell content.

    Returns:
        The parsed date, or ``None`` when ``value`` is empty or malformed.
    """
    if not value:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%d.%m.%Y").date()
    except ValueError:
        return None


def _midpoint(low: Decimal, high: Decimal) -> Decimal | None:
    """Compute the midpoint of a ``(min, max)`` price pair.

    Args:
        low: Parsed minimum price (``Decimal(0)`` when the cell was empty).
        high: Parsed maximum price (``Decimal(0)`` when the cell was empty).

    Returns:
        The arithmetic mean as a :class:`~decimal.Decimal`, or ``None`` when
        both values are zero (the row has no usable price).
    """
    if low <= 0 and high <= 0:
        return None
    if low <= 0:
        return high
    if high <= 0:
        return low
    return (low + high) / Decimal(2)


# --- Number parsing --------------------------------------------------------


_NBSP = "\xa0"
_DECIMAL_PARSE_ERRORS = (InvalidOperation, ValueError)


def _normalize_number(s: str) -> str:
    r"""Strip thousands separators and convert Turkish decimal commas to dots.

    Args:
        s: Raw cell text (``"32,40"``, ``"1.234,56"``, ``"\xa0"``, ...).

    Returns:
        A canonical string suitable for :class:`~decimal.Decimal`.
    """
    return s.replace(_NBSP, "").replace(" ", "").replace(".", "").replace(",", ".")


def _to_decimal(s: str) -> Decimal:
    """Convert a Turkish-formatted number to :class:`~decimal.Decimal`.

    Args:
        s: Raw cell text.

    Returns:
        The parsed amount, or ``Decimal(0)`` when ``s`` is empty / unparseable.
    """
    try:
        return Decimal(_normalize_number(s))
    except _DECIMAL_PARSE_ERRORS:
        return Decimal(0)


# --- DB / clock helpers ----------------------------------------------------


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_ankara`` already has any row for ``d``.

    Args:
        session: An open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` when at least one row exists for that bulletin date — the
        backfill loop uses this to skip days that are already covered.
    """
    try:
        res = await session.execute(
            text("SELECT 1 FROM prices_ankara WHERE bulletin_date = :d LIMIT 1"),
            {"d": d},
        )
    except Exception:
        await session.rollback()
        return False
    return res.scalar() is not None


def _today_istanbul() -> date:
    """Today's date in Europe/Istanbul — matches Ankara's bulletin clock.

    Returns:
        The local calendar date in the timezone ankara.bel.tr publishes
        against.
    """
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


# --- CLI entrypoint --------------------------------------------------------


async def _main() -> None:
    """Run the scraper standalone — useful for one-off scrapes and debugging."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    async with SessionLocal() as session:
        scraper = AnkaraScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Ankara scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`AnkaraScraper.run`.
    """
    return await AnkaraScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
