"""Scraper for the Istanbul wholesale-market daily price bulletin.

Source: https://tarim.ibb.istanbul/tr/istatistik/124/hal-fiyatlari.html

The visible page is just a shell; the daily table is loaded via a jQuery AJAX
GET against ``/inc/halfiyatlari/gunluk_fiyatlar.asp`` with the following query
parameters (mirrored from the page's inline JS):

* ``tarih`` — bulletin date in ISO ``YYYY-MM-DD`` form.
* ``kategori`` — product class: ``5`` (Meyve), ``6`` (Sebze), ``7`` (İthal Ürünler).
* ``tUsr`` / ``tPas`` / ``tVal`` — hard-coded API credentials baked into the page.
* ``HalTurId`` — market type id (``2`` for IBB's wholesale hal).

The response is a tiny HTML fragment::

    <table class="tableClass">
      <tr><th>Urun Adı</th><th>Birim</th>
          <th>En Düşük Fiyat</th><th>En Yüksek Fiyat</th></tr>
      <tr><td>Armut (Akça)</td><td>Kilogram</td>
          <td>155,00<span...> TL</span></td>
          <td>170,00<span...> TL</span></td></tr>
      ...
    </table>

An empty day yields just the header row. Each scheduled run backfills up to
``lookback_days`` of history, skipping days already present in
``prices_istanbul``.

Mapping to the project's :class:`ProductPrice` schema:

* ``product_name`` — text before any parenthetical (e.g. ``"Armut"``).
* ``product_variety`` — text inside the parenthetical (e.g. ``"Akça"``), or
  ``None`` when the row has none.
* ``product_category`` — ``None``. The source does not publish the
  Geleneksel/İyi Tarım/Organik axis that ``hal.gov.tr`` uses.
* ``average_price`` — midpoint of (min, max) as :class:`~decimal.Decimal`.
* ``unit_name`` — normalized to the project vocabulary ``Kg`` / ``Adet``.
* ``transaction_volume`` — ``None`` (source does not expose it).
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

# Public page (kept here for documentation / debugging — the scraper itself
# only hits the AJAX endpoint below).
PAGE_URL = "https://tarim.ibb.istanbul/tr/istatistik/124/hal-fiyatlari.html"
AJAX_URL = "https://tarim.ibb.istanbul/inc/halfiyatlari/gunluk_fiyatlar.asp"

# City name used internally by the scraper. The slug derived from this string
# (via :func:`local_bazaar.db.city_slug`) is ``istanbul`` and must match the
# row in the ``cities`` table.
CITY_NAME = "Istanbul"

# Static query parameters lifted from the page's inline JS. These look like
# credentials but are public — they are emitted verbatim into the HTML source
# served to every browser. We keep them in one place so a future rotation only
# needs a single edit.
_STATIC_PARAMS: dict[str, str] = {
    "tUsr": "M3yV353bZe",
    "tPas": "LA74sBcXERpdBaz",
    "tVal": "881f3dc3-7d08-40db-b45a-1275c0245685",
    "HalTurId": "2",
}

# Category dropdown values exposed by ``cbGunlukKategori`` on the page. We
# iterate over all of them per day so a single bulletin captures fruit,
# vegetable, and imported produce.
_CATEGORIES: tuple[str, ...] = ("5", "6", "7")

# Default lookback window. Each scheduled run ensures the last ``lookback_days``
# of bulletins are present in ``prices_istanbul`` and re-scrapes the gaps.
_DEFAULT_LOOKBACK_DAYS = 160

# Polite pause between per-category requests within a single day.
_DEFAULT_REQUEST_SLEEP = 0.3


class IstanbulHalScraper:
    """Scraper for the IBB Tarımsal Hizmetler daily hal-prices bulletin."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        request_sleep: float = _DEFAULT_REQUEST_SLEEP,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today (Europe/Istanbul) to
                backfill. Days that already have at least one row in
                ``prices_istanbul`` are skipped without an HTTP request.
            request_sleep: Seconds to wait between consecutive HTTP requests
                so we don't hammer ``tarim.ibb.istanbul``.
        """
        self.lookback_days = lookback_days
        self.request_sleep = request_sleep

    async def run(self, session: AsyncSession) -> int:
        """Backfill every missing day in the last ``lookback_days``.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across all newly-scraped days. ``0`` is a valid
            return — it means every day in the lookback window already has
            data (or the source has none to give for the gaps).
        """
        today = _today_istanbul()
        total = 0
        for offset in range(self.lookback_days):
            target = today - timedelta(days=offset)
            if await _has_data_for_date(session, target):
                continue
            total += await self._scrape_one_day(session, target)
        return total

    async def _scrape_one_day(self, session: AsyncSession, target: date) -> int:
        """Fetch one day's bulletin across every category and UPSERT it.

        Args:
            session: An open async DB session.
            target: The bulletin date to fetch (interpreted in Europe/Istanbul).

        Returns:
            Number of rows written for this day (``>= 0``).
        """
        prices: list[ProductPrice] = []
        async for p in self.iter_prices(target):
            prices.append(p)
        if not prices:
            log.info("ibb-istanbul: no rows for %s (source empty for this date)", target)
            return 0
        wrote = await upsert_prices(session, prices)
        log.info("ibb-istanbul: %s wrote %d rows", target, wrote)
        return wrote

    async def iter_prices(self, target_date: date) -> AsyncIterator[ProductPrice]:
        """Stream :class:`ProductPrice` records for one bulletin date.

        Args:
            target_date: The bulletin date to fetch.

        Yields:
            One :class:`ProductPrice` per parsed data row, across all three
            product categories (fruit, vegetable, imports). The
            ``bulletin_date`` of every emitted record is exactly
            ``target_date`` — unlike ``hal.gov.tr``, the IBB endpoint does not
            silently fall back to a different day for non-business dates; it
            simply returns an empty table.
        """
        async with http_client() as client:
            first = True
            for kategori in _CATEGORIES:
                if not first:
                    await asyncio.sleep(self.request_sleep)
                first = False
                rows = await self._fetch_category(client, target_date, kategori)
                log.info(
                    "ibb-istanbul: date=%s kategori=%s rows=%d",
                    target_date,
                    kategori,
                    len(rows),
                )
                for row in rows:
                    price = _row_to_price(row, target_date)
                    if price is not None:
                        yield price

    async def _fetch_category(
        self,
        client: httpx.AsyncClient,
        target_date: date,
        kategori: str,
    ) -> list[dict[str, str]]:
        """Fetch and parse the price table for one (date, category) pair.

        Args:
            client: The shared httpx client.
            target_date: Bulletin date to request.
            kategori: Category id (``"5"``, ``"6"``, ``"7"``).

        Returns:
            A list of raw row dicts as produced by :func:`_parse_table`. An
            empty list is returned both when the source has no data for the
            day and when the request fails with an HTTP error — failures are
            logged and swallowed so a single bad category doesn't sink the
            whole bulletin.
        """
        params: dict[str, str] = {
            "tarih": target_date.strftime("%Y-%m-%d"),
            "kategori": kategori,
            **_STATIC_PARAMS,
        }
        try:
            resp = await fetch_with_retry(
                client,
                "GET",
                AJAX_URL,
                params=params,
                headers={
                    # The site's own JS calls this endpoint via XHR; mimic the
                    # header so we look like the page rather than a random GET.
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": PAGE_URL,
                },
            )
        except httpx.HTTPStatusError as exc:
            log.warning(
                "ibb-istanbul: fetch failed for date=%s kategori=%s: %s",
                target_date,
                kategori,
                exc,
            )
            return []
        return _parse_table(resp.text)


# --- Module-level helpers (pure, easily testable) --------------------------


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract data rows from the IBB price fragment.

    Args:
        html: The raw HTML fragment returned by the AJAX endpoint.

    Returns:
        A list of dicts with keys ``product_name_raw``, ``unit_name``,
        ``min_price``, ``max_price``. The header row is skipped.
    """
    tree = HTMLParser(html)
    table = tree.css_first("table.tableClass") or tree.css_first("table")
    if table is None:
        return []

    rows: list[dict[str, str]] = []
    for tr in table.css("tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 4:
            # Header row (uses <th>, yielding zero <td>) or malformed row.
            continue
        rows.append(
            {
                "product_name_raw": cells[0],
                "unit_name": cells[1],
                "min_price": cells[2],
                "max_price": cells[3],
            }
        )
    return rows


def _row_to_price(row: dict[str, str], bulletin_date: date) -> ProductPrice | None:
    """Map a parsed table row to a :class:`ProductPrice`.

    Args:
        row: One dict produced by :func:`_parse_table`.
        bulletin_date: Bulletin date for the emitted record.

    Returns:
        A :class:`ProductPrice`, or ``None`` if the row is unusable (empty
        product name or both prices unparseable).
    """
    name_raw = row["product_name_raw"].strip()
    if not name_raw or not any(c.isalpha() for c in name_raw):
        return None
    product_name, product_variety = _split_name_and_variety(name_raw)
    min_p = _to_decimal(row["min_price"])
    max_p = _to_decimal(row["max_price"])
    if min_p == 0 and max_p == 0:
        # Both prices missing/zero — nothing useful to record.
        return None
    average = (min_p + max_p) / Decimal(2)
    # Quantize to 4 decimal places to match the NUMERIC(12,4) column.
    average = average.quantize(Decimal("0.0001"))
    return ProductPrice(
        city_name=CITY_NAME,
        bulletin_date=bulletin_date,
        product_name=product_name,
        product_variety=product_variety,
        product_category=None,
        average_price=average,
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit_name"]),
    )


_PAREN_RE = re.compile(r"^(?P<base>[^(]+?)\s*\((?P<inside>[^)]+)\)\s*(?P<tail>.*)$")


def _split_name_and_variety(raw: str) -> tuple[str, str | None]:
    """Split a raw product label into ``(name, variety_or_None)``.

    Examples:
        ``"Armut"`` → ``("Armut", None)``
        ``"Armut (Akça)"`` → ``("Armut", "Akça")``
        ``"Karpuz (1.Kalite)"`` → ``("Karpuz", "1.Kalite")``
        ``"Kayısı I."`` → ``("Kayısı I.", None)``

    Args:
        raw: The full text of the first cell.

    Returns:
        A ``(product_name, product_variety)`` tuple. ``product_variety`` is
        ``None`` when the label has no parenthetical part.
    """
    raw = raw.strip()
    m = _PAREN_RE.match(raw)
    if not m:
        return raw, None
    base = m.group("base").strip()
    inside = m.group("inside").strip()
    tail = m.group("tail").strip()
    # If the source appended extra text after the parenthetical, fold it back
    # into the base name so we don't silently drop it.
    if tail:
        base = f"{base} {tail}".strip()
    return base, (inside or None)


_UNIT_NORMALIZATION = {
    "kilogram": "Kg",
    "kg": "Kg",
    "adet": "Adet",
}


def _normalize_unit(value: str) -> str:
    """Normalize a Turkish unit label to the project vocabulary (``Kg``/``Adet``).

    Args:
        value: Raw unit cell text (e.g. ``"Kilogram"``, ``"Adet"``).

    Returns:
        Canonical unit name. Unknown values are returned title-cased and
        stripped — better to keep the data than to drop it.
    """
    key = value.strip().lower()
    return _UNIT_NORMALIZATION.get(key, value.strip().title())


# --- Number parsing --------------------------------------------------------


_NBSP = "\xa0"
_DECIMAL_PARSE_ERRORS = (InvalidOperation, ValueError)


def _normalize_number(s: str) -> str:
    """Strip currency markers and convert a Turkish decimal string to ``X.Y``.

    The source serializes prices as ``"155,00 TL"`` (sometimes wrapped in a
    ``<span>``). After tag-stripping by selectolax we still see the ``TL``
    suffix and the Turkish thousands/decimal punctuation. This helper removes
    everything that isn't a digit, a sign, or the decimal separator.

    Args:
        s: Raw cell text.

    Returns:
        A string suitable for :class:`~decimal.Decimal` (e.g. ``"155.00"``).
    """
    cleaned = (
        s.replace(_NBSP, "")
        .replace("TL", "")
        .replace("₺", "")
        .replace(" ", "")
    )
    # Turkish format: thousands separator '.', decimal separator ','.
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return cleaned


def _to_decimal(s: str) -> Decimal:
    """Parse a Turkish-formatted price cell to :class:`~decimal.Decimal`.

    Args:
        s: Raw price text from the table (e.g. ``"155,00 TL"``).

    Returns:
        The parsed price, or ``Decimal(0)`` if the cell is empty or unparseable.
        Callers treat zero as "missing" and skip the row when both endpoints
        are zero.
    """
    cleaned = _normalize_number(s)
    if not cleaned:
        return Decimal(0)
    try:
        return Decimal(cleaned)
    except _DECIMAL_PARSE_ERRORS:
        return Decimal(0)


# --- DB / clock helpers ----------------------------------------------------


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_istanbul`` already has any row for ``d``.

    Args:
        session: An open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` when at least one row exists for that bulletin date — the
        backfill loop uses this to skip days that are already covered.
        ``False`` if the table itself does not exist yet (a fresh database
        will create it on the first :func:`upsert_prices` call).
    """
    try:
        res = await session.execute(
            text("SELECT 1 FROM prices_istanbul WHERE bulletin_date = :d LIMIT 1"),
            {"d": d},
        )
    except Exception:
        # Table is created lazily by upsert_prices(); on a fresh DB the first
        # call here will fail. Treat that as "no data yet" and let the scrape
        # proceed — upsert_prices() will create the table.
        await session.rollback()
        return False
    return res.scalar() is not None


def _today_istanbul() -> date:
    """Today's date in Europe/Istanbul — matches the source's bulletin clock.

    Returns:
        The local calendar date in the timezone the IBB page publishes against.
    """
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


# --- CLI entrypoint --------------------------------------------------------


async def _main() -> None:
    """Run the scraper standalone — useful for one-off scrapes and debugging."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = IstanbulHalScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Istanbul-bulletin scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`IstanbulHalScraper.run`.
    """
    return await IstanbulHalScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
