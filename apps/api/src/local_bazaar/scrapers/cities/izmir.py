"""Scraper for the İzmir Büyükşehir Belediyesi hal daily bulletin.

Source: https://eislem.izmir.bel.tr/tr/HalFiyatlari/

The page exposes a plain ASP.NET MVC form (``method="get"``) with three
filters: ``date`` (``YYYY-MM-DD``), ``tip`` (1=Sebze, 2=Meyve, 3=İthal), and
``aranacak`` (free-text product filter, unused here). Submitting reloads the
same path with the params appended; the server renders a
``<table class="table table-condensed">`` with columns::

    Tip | Adı | Birimi | En Az | En Çok | Ortalama

Crucially the source publishes a real ``Ortalama`` (average) column — we use
it directly as ``average_price`` without computing a midpoint. The ``Tip``
cell ("SEBZE" / "MEYVE" / "İTHAL") becomes the ``product_category``.
"""

from __future__ import annotations

import asyncio
import logging
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
    is_allowed,
    upsert_prices,
)

log = logging.getLogger(__name__)

CITY_NAME = "Izmir"
_SLUG = "izmir"
_URL = "https://eislem.izmir.bel.tr/tr/HalFiyatlari/"
_TIPS: tuple[int, ...] = (1, 2, 3)  # Sebze / Meyve / İthal
_DEFAULT_LOOKBACK_DAYS = 160
_REQUEST_SLEEP = 0.3
_DAY_SLEEP = 0.5


class IzmirScraper:
    """Scrape İzmir's hal daily bulletins."""

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
            request_sleep: Pause between sequential category fetches per day.
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
            Total rows written across newly-scraped days. ``0`` is also
            returned when ``robots.txt`` disallows this run entirely.
        """
        if not await is_allowed(_URL):
            log.warning("izmir: robots.txt disallows %s — skipping this run.", _URL)
            return 0
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
                    log.info("izmir: %s wrote %d rows", target, wrote)
                else:
                    log.info("izmir: %s no rows (source empty)", target)
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
            One :class:`ProductPrice` per row across all 3 categories.
        """
        for i, tip in enumerate(_TIPS):
            params = {"date": target.strftime("%Y-%m-%d"), "tip": str(tip)}
            try:
                resp = await fetch_with_retry(client, "GET", _URL, params=params)
            except Exception as exc:
                log.warning("izmir: GET %s tip=%s failed: %s", target, tip, exc)
                continue
            for row in _parse_table(resp.text):
                yield _row_to_price(row, target)
            if i < len(_TIPS) - 1:
                await asyncio.sleep(self.request_sleep)


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract product rows from the result table.

    Args:
        html: Raw HTML response body.

    Returns:
        A list of dicts with keys category, product, unit, low, high, average.
    """
    tree = HTMLParser(html)
    table = tree.css_first("table.table-condensed") or tree.css_first("table")
    if table is None:
        return []
    rows: list[dict[str, str]] = []
    for tr in table.css("tbody tr") or table.css("tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 6:
            continue
        rows.append(
            {
                "category": cells[0],
                "product": cells[1],
                "unit": cells[2],
                "low": cells[3],
                "high": cells[4],
                "average": cells[5],
            }
        )
    return rows


def _row_to_price(row: dict[str, str], bulletin_date: date) -> ProductPrice:
    """Map a parsed row dict to a :class:`ProductPrice` record.

    Args:
        row: Output of :func:`_parse_table` for a single ``<tr>``.
        bulletin_date: The bulletin date this row belongs to.

    Returns:
        One :class:`ProductPrice` ready for UPSERT.
    """
    return ProductPrice(
        city_name=CITY_NAME,
        bulletin_date=bulletin_date,
        product_name=_titlecase_tr(row["product"]),
        product_variety=None,
        product_category=_titlecase_tr(row["category"]) or None,
        average_price=_to_decimal(row["average"]),
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit"]),
    )


def _titlecase_tr(s: str) -> str:
    """Title-case a Turkish-uppercased string while leaving multi-word input intact.

    Args:
        s: Source string (typically ALL CAPS, e.g. ``"BARBUNYA TAZE"``).

    Returns:
        A title-cased version (``"Barbunya Taze"``) for readable display.
    """
    return " ".join(w.capitalize() for w in s.strip().split())


def _normalize_unit(unit: str) -> str:
    """Normalize the source's ``Birimi`` cell to ``Kg`` / ``Adet``.

    Args:
        unit: Raw birim text (``"KG"``, ``"ADET"``, ...).

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
    r"""Strip currency suffixes and convert Turkish decimal commas to dots.

    Args:
        s: Raw cell text (``"30,0 TL"``, ``"1.234,56 ₺"``, ``"\xa0"``, ...).

    Returns:
        A canonical string suitable for :class:`decimal.Decimal`.
    """
    cleaned = s.replace(_NBSP, "").replace(" ", "").replace("₺", "").replace("TL", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    return cleaned


def _to_decimal(s: str) -> Decimal:
    """Parse a Turkish-formatted number into :class:`Decimal`.

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
    """Return ``True`` if ``prices_izmir`` already has any row for ``d``.

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
    """Run the İzmir scraper standalone — useful for one-off scrapes."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = IzmirScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the İzmir scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`IzmirScraper.run`.
    """
    return await IzmirScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
