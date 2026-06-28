"""Scraper for the Şanlıurfa Büyükşehir Belediyesi hal daily bulletin.

Source: https://halfiyatlari.sanliurfa.bel.tr/

The page is a Laravel-style search form. The base URL renders only the form
shell; submitting with the right query parameters returns a server-rendered
``<table class="custom-table">`` with rows for the requested date range and
product type.

Required query params::

    ?search=1
    &start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &product_type_id=N         # 1=Sebze, 2=Meyve

Result columns::

    Ürün Adı | Ürün Türü | Birim | En Düşük Fiyat (₺) | En Yüksek Fiyat (₺) | Tarih

Prices use a DOT as the decimal separator (``"90.00"``) — unlike most Turkish
sources which use a comma. The ``Tarih`` cell is authoritative for
``bulletin_date``. Variety in parens (``Biber Kapya (Sera)``) is split out.
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

CITY_NAME = "Şanlıurfa"
_SLUG = "sanliurfa"
_URL = "https://halfiyatlari.sanliurfa.bel.tr/"
_PRODUCT_TYPES: tuple[int, ...] = (1, 2)  # Sebze / Meyve
_DEFAULT_LOOKBACK_DAYS = 160
_REQUEST_SLEEP = 0.3
_DAY_SLEEP = 0.5


class SanliurfaScraper:
    """Scrape Şanlıurfa's hal daily bulletins."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        request_sleep: float = _REQUEST_SLEEP,
        day_sleep: float = _DAY_SLEEP,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill.
            request_sleep: Pause between sequential product-type fetches per day.
            day_sleep: Pause between sequential day fetches.
        """
        self.lookback_days = lookback_days
        self.request_sleep = request_sleep
        self.day_sleep = day_sleep

    async def run(self, session: AsyncSession) -> int:
        """Backfill every missing bulletin in the lookback window.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across newly-scraped days.
        """
        today = _today_istanbul()
        total = 0
        async with http_client() as client:
            for offset in range(self.lookback_days):
                target = today - timedelta(days=offset)
                if await _has_data_for_date(session, target):
                    continue
                prices: list[ProductPrice] = []
                async for p in self._iter_day(client, target):
                    prices.append(p)
                if prices:
                    wrote = await upsert_prices(session, prices)
                    total += wrote
                    log.info("sanliurfa: %s wrote %d rows", target, wrote)
                else:
                    log.info("sanliurfa: %s no rows (source empty)", target)
                if offset < self.lookback_days - 1:
                    await asyncio.sleep(self.day_sleep)
        return total

    async def _iter_day(
        self, client: httpx.AsyncClient, target: date
    ) -> AsyncIterator[ProductPrice]:
        """Yield :class:`ProductPrice` records for one bulletin date.

        Args:
            client: Open ``httpx.AsyncClient`` from :func:`http_client`.
            target: Bulletin date to fetch.

        Yields:
            One :class:`ProductPrice` per row across both product types.
        """
        iso = target.strftime("%Y-%m-%d")
        for i, ptype in enumerate(_PRODUCT_TYPES):
            params = {
                "search": "1",
                "start_date": iso,
                "end_date": iso,
                "product_type_id": str(ptype),
            }
            try:
                resp = await fetch_with_retry(client, "GET", _URL, params=params)
            except Exception as exc:
                log.warning("sanliurfa: GET %s product_type_id=%s failed: %s", target, ptype, exc)
                continue
            for row in _parse_table(resp.text):
                yield _row_to_price(row, target)
            if i < len(_PRODUCT_TYPES) - 1:
                await asyncio.sleep(self.request_sleep)


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract product rows from the result table.

    Args:
        html: Raw HTML response body.

    Returns:
        A list of dicts with keys product, category, unit, low, high, date.
    """
    tree = HTMLParser(html)
    table = tree.css_first("table.custom-table") or tree.css_first("table")
    if table is None:
        return []
    rows: list[dict[str, str]] = []
    for tr in table.css("tbody tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 6:
            continue
        rows.append(
            {
                "product": cells[0],
                "category": cells[1],
                "unit": cells[2],
                "low": cells[3],
                "high": cells[4],
                "date": cells[5],
            }
        )
    return rows


_VARIETY_RE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<variety>[^()]+)\)\s*$")


def _split_name_and_variety(raw: str) -> tuple[str, str | None]:
    """Split ``"Biber Kapya (Sera)"`` into ``("Biber Kapya", "Sera")``.

    Args:
        raw: The ``Ürün Adı`` cell as published.

    Returns:
        A ``(name, variety)`` tuple. ``variety`` is ``None`` when the cell
        contains no parenthetical.
    """
    m = _VARIETY_RE.match(raw)
    if not m:
        return raw.strip(), None
    return m.group("name").strip(), m.group("variety").strip()


def _row_to_price(row: dict[str, str], bulletin_date: date) -> ProductPrice:
    """Map a parsed row dict to a :class:`ProductPrice` record.

    Args:
        row: Output of :func:`_parse_table` for a single ``<tr>``.
        bulletin_date: The bulletin date we requested. The row's ``Tarih`` cell
            is used to override this when present and parseable, so requests
            for non-publication days fall back to whatever the source returns.

    Returns:
        One :class:`ProductPrice` ready for UPSERT.
    """
    name, variety = _split_name_and_variety(row["product"])
    low = _to_decimal(row["low"])
    high = _to_decimal(row["high"])
    average = ((low + high) / Decimal(2)).quantize(Decimal("0.0001"))
    parsed_date = _parse_tr_date(row.get("date", "")) or bulletin_date
    return ProductPrice(
        city_name=CITY_NAME,
        bulletin_date=parsed_date,
        product_name=name,
        product_variety=variety,
        product_category=row["category"] or None,
        average_price=average,
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit"]),
    )


def _parse_tr_date(s: str) -> date | None:
    """Parse the source's ``dd.mm.yyyy`` ``Tarih`` cell.

    Args:
        s: Raw cell text.

    Returns:
        The parsed :class:`date`, or ``None`` if the cell is empty / malformed.
    """
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except ValueError:
        return None


def _normalize_unit(unit: str) -> str:
    """Normalize the source's ``Birim`` cell to ``Kg`` / ``Adet``.

    Args:
        unit: Raw birim text (``"kg"``, ``"Adet"``, ...).

    Returns:
        Canonical unit string.
    """
    cleaned = unit.strip().lower()
    if cleaned in {"ad", "adet"}:
        return "Adet"
    if cleaned in {"kg", "kg.", "kğ"}:
        return "Kg"
    return unit.strip() or "Kg"


_NBSP = "\xa0"


def _normalize_number(s: str) -> str:
    r"""Normalize a numeric cell for :class:`Decimal` parsing.

    Şanlıurfa publishes prices with a DOT as decimal separator (``"90.00"``),
    unlike most other Turkish hal sources. We therefore only strip currency
    suffixes and whitespace — no comma↔dot swap.

    Args:
        s: Raw cell text (``"90.00"``, ``"1234.56 ₺"``, ``"\xa0"``, ...).

    Returns:
        A canonical string suitable for :class:`decimal.Decimal`.
    """
    return s.replace(_NBSP, "").replace(" ", "").replace("₺", "").replace("TL", "")


def _to_decimal(s: str) -> Decimal:
    """Parse a numeric cell into :class:`Decimal`.

    Args:
        s: Raw cell text.

    Returns:
        The parsed :class:`Decimal`, or ``Decimal(0)`` on parse failure.
    """
    try:
        return Decimal(_normalize_number(s))
    except InvalidOperation, ValueError:
        return Decimal(0)


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_sanliurfa`` already has any row for ``d``.

    Args:
        session: Open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` if at least one row exists; ``False`` otherwise (also ``False``
        when the table does not yet exist).
    """
    try:
        res = await session.execute(
            text(f"SELECT 1 FROM prices_{_SLUG} WHERE bulletin_date = :d LIMIT 1"),
            {"d": d},
        )
        return res.scalar() is not None
    except Exception:
        await session.rollback()
        return False


def _today_istanbul() -> date:
    """Today's date in Europe/Istanbul.

    Returns:
        The local calendar date for the Turkish business day.
    """
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


async def _main() -> None:
    """Run the Şanlıurfa scraper standalone — useful for one-off scrapes."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = SanliurfaScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Şanlıurfa scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`SanliurfaScraper.run`.
    """
    return await SanliurfaScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
