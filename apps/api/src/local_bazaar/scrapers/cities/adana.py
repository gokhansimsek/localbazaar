"""Scraper for the Adana Büyükşehir Belediyesi hal daily bulletin.

Source: https://www.adana.bel.tr/tr/hal-fiyat-listesi

Adana's site is structured in two layers:

1. **Listing pages** at ``/tr/hal-fiyat-listesi[/offset]`` paginate bulletin
   announcements (5 entries per page; offset is the row index — 0, 5, 10 …).
   Each entry is a card containing a date (``"DD/MM/YYYY"``) and a link to the
   detail page for that day (``/tr/hal-detay/<id>``).
2. **Detail pages** at ``/tr/hal-detay/<id>`` render the actual bulletin as
   two ``<table class="table table-striped">`` blocks. Both tables share the
   same column layout::

        Cinsi | Br | En Düşük | En Yüksek

   The detail page's header (``<h4>DD/MM/YYYY Tarihli ...</h4>``) is the
   authoritative bulletin date.

The scraper walks the listing pages, collects ``(date, detail_id)`` pairs
within the lookback window, skips dates already in ``prices_adana``, then
fetches each missing detail page to extract rows. Prices are min/max with a
DOT decimal separator; we persist the midpoint as ``average_price``. Variety
in parentheses (``BİBER(ÜÇ BURUN KÖY)``) is split out into ``product_variety``.
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

CITY_NAME = "Adana"
_SLUG = "adana"
_LISTING_URL = "https://www.adana.bel.tr/tr/hal-fiyat-listesi"
_DETAIL_URL = "https://www.adana.bel.tr/tr/hal-detay/{detail_id}"
_DETAIL_LINK_RE = re.compile(r"/tr/hal-detay/(\d+)")
_LISTING_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_DETAIL_HEADER_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s*Tarihli")
_PAGE_SIZE = 5
_DEFAULT_LOOKBACK_DAYS = 160
_MAX_LISTING_PAGES = 100
_REQUEST_SLEEP = 0.4


class AdanaScraper:
    """Scrape Adana's hal daily bulletins via the listing + detail page pair."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        request_sleep: float = _REQUEST_SLEEP,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill.
            request_sleep: Pause between sequential HTTP requests.
        """
        self.lookback_days = lookback_days
        self.request_sleep = request_sleep

    async def run(self, session: AsyncSession) -> int:
        """Discover detail page IDs in the lookback window, fetch the missing ones, UPSERT.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across newly-scraped days.
        """
        today = _today_istanbul()
        cutoff = today - timedelta(days=self.lookback_days)
        total = 0

        async with http_client() as client:
            entries = await self._discover_entries(client, cutoff)
            log.info("adana: found %d listing entries within lookback", len(entries))

            for entry_date, detail_id in entries:
                if await _has_data_for_date(session, entry_date):
                    continue
                prices: list[ProductPrice] = []
                async for p in self._iter_detail(client, detail_id, entry_date):
                    prices.append(p)
                if prices:
                    wrote = await upsert_prices(session, prices)
                    total += wrote
                    log.info("adana: %s (id=%s) wrote %d rows", entry_date, detail_id, wrote)
                else:
                    log.info("adana: %s (id=%s) no rows (detail empty)", entry_date, detail_id)
                await asyncio.sleep(self.request_sleep)
        return total

    async def _discover_entries(
        self, client: httpx.AsyncClient, cutoff: date
    ) -> list[tuple[date, str]]:
        """Walk the listing pages and collect ``(date, detail_id)`` pairs.

        Args:
            client: Open ``httpx.AsyncClient`` from :func:`http_client`.
            cutoff: Stop walking once an entry's date falls on or before this
                date.

        Returns:
            A list of ``(bulletin_date, detail_id)`` pairs newest-first.
        """
        out: list[tuple[date, str]] = []
        for page_idx in range(_MAX_LISTING_PAGES):
            offset = page_idx * _PAGE_SIZE
            url = _LISTING_URL if offset == 0 else f"{_LISTING_URL}/{offset}"
            try:
                resp = await fetch_with_retry(client, "GET", url)
            except Exception as exc:
                log.warning("adana: listing GET %s failed: %s", url, exc)
                break
            page_entries = _parse_listing(resp.text)
            if not page_entries:
                break
            for d, detail_id in page_entries:
                if d <= cutoff:
                    return out
                out.append((d, detail_id))
            await asyncio.sleep(self.request_sleep)
        return out

    async def _iter_detail(
        self,
        client: httpx.AsyncClient,
        detail_id: str,
        bulletin_date: date,
    ) -> AsyncIterator[ProductPrice]:
        """Fetch one detail page and yield :class:`ProductPrice` records.

        Args:
            client: Open ``httpx.AsyncClient``.
            detail_id: The numeric id from the listing page (e.g. ``"2611"``).
            bulletin_date: The date the listing page recorded for this id. The
                detail page's own header overrides it when present.

        Yields:
            One :class:`ProductPrice` per row across all tables on the page.
        """
        url = _DETAIL_URL.format(detail_id=detail_id)
        try:
            resp = await fetch_with_retry(client, "GET", url)
        except Exception as exc:
            log.warning("adana: detail GET %s failed: %s", url, exc)
            return
        effective_date = _parse_detail_header_date(resp.text) or bulletin_date
        for row in _parse_detail_tables(resp.text):
            yield _row_to_price(row, effective_date)


def _parse_listing(html: str) -> list[tuple[date, str]]:
    """Extract ``(bulletin_date, detail_id)`` pairs from a listing page.

    Args:
        html: Raw HTML response body.

    Returns:
        A list of pairs in document order (newest first within the page).
    """
    tree = HTMLParser(html)
    out: list[tuple[date, str]] = []
    for card in tree.css("div.card.event-list-box"):
        card_html = card.html or ""
        date_match = _LISTING_DATE_RE.search(card_html)
        link_match = _DETAIL_LINK_RE.search(card_html)
        if not date_match or not link_match:
            continue
        d, m, y = date_match.groups()
        try:
            bulletin_date = date(int(y), int(m), int(d))
        except ValueError:
            continue
        out.append((bulletin_date, link_match.group(1)))
    return out


def _parse_detail_header_date(html: str) -> date | None:
    """Read the bulletin date from the detail page header.

    Args:
        html: Raw HTML response body.

    Returns:
        The parsed :class:`date`, or ``None`` if no matching header is found.
    """
    m = _DETAIL_HEADER_DATE_RE.search(html)
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d))
    except ValueError:
        return None


def _parse_detail_tables(html: str) -> list[dict[str, str]]:
    """Extract product rows from every striped table on a detail page.

    Args:
        html: Raw HTML response body.

    Returns:
        A list of dicts with keys product, unit, low, high.
    """
    tree = HTMLParser(html)
    rows: list[dict[str, str]] = []
    for table in tree.css("table.table-striped"):
        for tr in table.css("tbody tr"):
            cells = [c.text(strip=True) for c in tr.css("td")]
            if len(cells) < 4:
                continue
            rows.append(
                {
                    "product": cells[0],
                    "unit": cells[1],
                    "low": cells[2],
                    "high": cells[3],
                }
            )
    return rows


_VARIETY_RE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<variety>[^()]+)\)\s*$")


def _split_name_and_variety(raw: str) -> tuple[str, str | None]:
    """Split ``"BİBER(ÜÇ BURUN KÖY)"`` into ``("Biber", "Üç Burun Köy")``.

    Args:
        raw: The ``Cinsi`` cell as published.

    Returns:
        A title-cased ``(name, variety)`` tuple. ``variety`` is ``None`` when
        no parenthetical is present.
    """
    cleaned = raw.strip()
    m = _VARIETY_RE.match(cleaned)
    if not m:
        return _titlecase_tr(cleaned), None
    return _titlecase_tr(m.group("name")), _titlecase_tr(m.group("variety"))


def _row_to_price(row: dict[str, str], bulletin_date: date) -> ProductPrice:
    """Map a parsed row dict to a :class:`ProductPrice` record.

    Args:
        row: Output of :func:`_parse_detail_tables` for a single ``<tr>``.
        bulletin_date: The bulletin date this row belongs to.

    Returns:
        One :class:`ProductPrice` ready for UPSERT.
    """
    name, variety = _split_name_and_variety(row["product"])
    low = _to_decimal(row["low"])
    high = _to_decimal(row["high"])
    average = ((low + high) / Decimal(2)).quantize(Decimal("0.0001"))
    return ProductPrice(
        city_name=CITY_NAME,
        bulletin_date=bulletin_date,
        product_name=name,
        product_variety=variety,
        product_category=None,
        average_price=average,
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit"]),
    )


def _titlecase_tr(s: str) -> str:
    """Title-case an ALL-CAPS Turkish string for readable display.

    Args:
        s: Source string (typically ALL CAPS, e.g. ``"BİBER KAPYA"``).

    Returns:
        A title-cased version (``"Biber Kapya"``).
    """
    return " ".join(w.capitalize() for w in s.strip().split())


def _normalize_unit(unit: str) -> str:
    """Normalize the source's ``Br`` cell to ``Kg`` / ``Adet``.

    Args:
        unit: Raw birim text (``"KG"``, ``"AD"``, ...).

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

    Adana publishes prices with a DOT decimal separator (``"10.00"``), so we
    only strip currency suffixes and whitespace.

    Args:
        s: Raw cell text.

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
    """Return ``True`` if ``prices_adana`` already has any row for ``d``.

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
    """Run the Adana scraper standalone — useful for one-off scrapes."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = AdanaScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Adana scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`AdanaScraper.run`.
    """
    return await AdanaScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
