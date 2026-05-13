"""Scraper for the Kocaeli Büyükşehir Belediyesi central hal daily bulletin.

Source: https://www.kocaeli.bel.tr/hal-fiyatlari/d-YYYY-MM-DD-h-1.html

The page is plain server-rendered HTML — no JavaScript required. The URL path
encodes the bulletin date and a hall index. Probing shows only ``h-1`` carries
data; ``h-2/h-3/...`` render the same layout shell with no rows. We therefore
only fetch ``h-1`` for each requested date.

Table layout (single ``<table>`` per page)::

    Ürün Adı | Kategori | Birim | En az | En çok
    Armut (Deveci) | Meyve | Kg | 90 | 90
    Asma Yaprağı  | Sebze | Kg | 70 | 125
    Ananas        | Meyve | Ad  | 150 | 165

The source publishes only a min / max range — we persist the midpoint as
``average_price``. ``Kategori`` ("Sebze" / "Meyve") becomes ``product_category``.
Variety in parentheses (``Armut (Deveci)``) is split out into ``product_variety``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

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

CITY_NAME = "Kocaeli"
_SLUG = "kocaeli"
_URL_TEMPLATE = "https://www.kocaeli.bel.tr/hal-fiyatlari/d-{date}-h-1.html"
_DEFAULT_LOOKBACK_DAYS = 160
_DAY_SLEEP = 0.5


class KocaeliScraper:
    """Scrape Kocaeli's central hal daily bulletins."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        day_sleep: float = _DAY_SLEEP,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: Backfill window in calendar days. Days already
                present in ``prices_kocaeli`` are skipped.
            day_sleep: Seconds between sequential day fetches.
        """
        self.lookback_days = lookback_days
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
                    log.info("kocaeli: %s wrote %d rows", target, wrote)
                else:
                    log.info("kocaeli: %s no rows (source empty)", target)
                if offset < self.lookback_days - 1:
                    await asyncio.sleep(self.day_sleep)
        return total

    async def _iter_day(self, client, target: date) -> AsyncIterator[ProductPrice]:  # noqa: ANN001
        """Yield :class:`ProductPrice` records for one bulletin date.

        Args:
            client: Open ``httpx.AsyncClient`` from :func:`http_client`.
            target: Bulletin date to fetch.

        Yields:
            One :class:`ProductPrice` per parsed table row.
        """
        url = _URL_TEMPLATE.format(date=target.strftime("%Y-%m-%d"))
        try:
            resp = await fetch_with_retry(client, "GET", url)
        except Exception as exc:
            log.warning("kocaeli: GET %s failed: %s", url, exc)
            return
        for row in _parse_table(resp.text):
            yield _row_to_price(row, target)


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract product rows from the first ``<table>`` on the page.

    Args:
        html: Raw HTML response body.

    Returns:
        A list of dicts with keys product, category, unit, low, high.
    """
    tree = HTMLParser(html)
    table = tree.css_first("table")
    if table is None:
        return []
    rows: list[dict[str, str]] = []
    for tr in table.css("tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 5:
            continue
        if cells[0].lower().startswith("ürün") or cells[0] == "Ürün Adı":
            continue  # header row
        rows.append(
            {
                "product": cells[0],
                "category": cells[1],
                "unit": cells[2],
                "low": cells[3],
                "high": cells[4],
            }
        )
    return rows


_VARIETY_RE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<variety>[^()]+)\)\s*$")


def _split_name_and_variety(raw: str) -> tuple[str, str | None]:
    """Split ``"Armut (Deveci)"`` into ``("Armut", "Deveci")``.

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
        product_category=row["category"] or None,
        average_price=average,
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit"]),
    )


def _normalize_unit(unit: str) -> str:
    """Normalize the source's ``Birim`` cell to ``Kg`` / ``Adet``.

    Args:
        unit: Raw birim text (``"Kg"``, ``"Ad"``, ``"kg"``, ...).

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
    r"""Strip Turkish thousand-separator dots and convert commas to dots.

    Args:
        s: Raw cell text — may contain ``\xa0``, ``"TL"`` / ``"₺"`` suffixes,
            and Turkish ``"1.234,56"`` formatting.

    Returns:
        A string suitable for :class:`decimal.Decimal`.
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
    except (InvalidOperation, ValueError):
        return Decimal(0)


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_kocaeli`` already has any row for ``d``.

    Args:
        session: Open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` if at least one row exists; ``False`` otherwise (also ``False``
        when the table does not yet exist — first-ever run).
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
    """Run the Kocaeli scraper standalone — useful for one-off scrapes."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = KocaeliScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Kocaeli scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`KocaeliScraper.run`.
    """
    return await KocaeliScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
