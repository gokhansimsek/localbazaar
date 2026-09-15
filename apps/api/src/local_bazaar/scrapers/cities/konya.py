"""Scraper for the Konya Metropolitan Municipality wholesale-market (hal) price list.

Source: https://www.konya.bel.tr/hal-fiyatlari

How the page works
------------------
- Server-rendered HTML (Laravel app — ``x-powered-by: BenimSehrim``). No JS rendering
  required.
- A ``<form action="/hal-fiyatlari">`` with a single ``<select name="tarih">`` enumerates
  every published bulletin. Submitting the form is just a GET with
  ``?tarih=YYYY-MM-DD``. Dates not in the select return HTTP 500, so the available-date
  list is the source of truth for backfills.
- The page renders the bulletin in two side-by-side tables:
    * **SEBZE FİYATLARI** (vegetables) — 4 columns: Ürün / Birim / En Düşük / En Yüksek
    * **MEYVE FİYATLARI** (fruits) — same 4 columns
  We use the section header as the ``product_category`` ("Sebze" / "Meyve") since this
  source does not publish the Geleneksel/İyi Tarım/Organik distinction that hal.gov.tr
  does.
- Product names embed the variety in parentheses, e.g. ``ELMA (GRANNY SMİTH)``. We
  split that into ``product_name="ELMA"`` and ``product_variety="GRANNY SMİTH"``.
- The source publishes a low/high range, not a single average. We store the midpoint
  as ``average_price`` and discard rows where neither bound parses.
- No pagination — both tables render in full on a single page.

Each scheduled run backfills the last ``lookback_days`` (default 160) of bulletins.
Days already present in ``prices_konya`` are skipped without an HTTP request.
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
from selectolax.parser import HTMLParser, Node
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

URL = "https://www.konya.bel.tr/hal-fiyatlari"
CITY_NAME = "Konya"

# Default lookback window — every run ensures the last ``lookback_days`` of
# bulletins are present in ``prices_konya`` and re-scrapes the gaps.
_DEFAULT_LOOKBACK_DAYS = 160

# Header text → product_category. We use the Turkish category name verbatim, mirroring
# how the national scraper preserves source-language category values.
_VEG_CATEGORY = "Sebze"
_FRUIT_CATEGORY = "Meyve"

# Page sections we recognize. Anything else is ignored so layout drift fails closed.
_SECTION_HEADERS = {
    "SEBZE FİYATLARI": _VEG_CATEGORY,
    "MEYVE FİYATLARI": _FRUIT_CATEGORY,
}


class KonyaScraper:
    """Scraper for the daily wholesale-market price list at konya.bel.tr."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        page_sleep: float = 0.5,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill. Days already
                present in ``prices_konya`` are skipped without an HTTP request.
            page_sleep: Seconds to wait between per-date requests so we don't hammer
                the source.
        """
        self.lookback_days = lookback_days
        self.page_sleep = page_sleep

    async def run(self, session: AsyncSession) -> int:
        """Backfill every missing day in the last ``lookback_days``.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across all newly-scraped days. ``0`` is a valid
            return — it means every published bulletin in the lookback window is
            already in the DB (or the source has nothing to give), or that
            ``robots.txt`` disallows this run entirely.
        """
        if not await is_allowed(URL):
            log.warning("konya.bel.tr: robots.txt disallows %s — skipping this run.", URL)
            return 0
        today = _today_istanbul()
        cutoff = today - timedelta(days=self.lookback_days - 1)

        async with http_client() as client:
            try:
                resp = await fetch_with_retry(client, "GET", URL)
            except httpx.HTTPError as exc:
                log.warning("konya.bel.tr: landing page fetch failed: %s", exc)
                return 0
            landing_html = resp.text
            available = _extract_available_dates(landing_html)
            if not available:
                log.warning(
                    "konya.bel.tr: no dates parsed from landing page — layout may have "
                    "changed; skipping run."
                )
                return 0
            log.info(
                "konya.bel.tr: %d bulletins available; backfilling those within %s..%s",
                len(available),
                cutoff,
                today,
            )

            total = 0
            for bulletin_date in sorted(available, reverse=True):
                if bulletin_date > today or bulletin_date < cutoff:
                    continue
                if await _has_data_for_date(session, bulletin_date):
                    continue
                # The most recent date is already in landing_html — reuse it to save
                # one request.
                if bulletin_date == max(available):
                    html = landing_html
                else:
                    html = await self._fetch_date(client, bulletin_date)
                    if html is None:
                        continue
                    await asyncio.sleep(self.page_sleep)
                prices = list(self._parse_bulletin(html, bulletin_date))
                if not prices:
                    log.info(
                        "konya.bel.tr: %s parsed 0 rows (empty bulletin?)",
                        bulletin_date,
                    )
                    continue
                wrote = await upsert_prices(session, prices)
                log.info("konya.bel.tr: %s wrote %d rows", bulletin_date, wrote)
                total += wrote
            return total

    async def iter_prices(
        self,
        target_date: date | None = None,
    ) -> AsyncIterator[ProductPrice]:
        """Stream :class:`ProductPrice` records for one bulletin date.

        Args:
            target_date: Bulletin date to fetch. ``None`` means whatever the landing
                page currently renders (the most recent published bulletin).

        Yields:
            One :class:`ProductPrice` per parsed data row across both the vegetables
            and the fruits tables.
        """
        async with http_client() as client:
            if target_date is None:
                resp = await fetch_with_retry(client, "GET", URL)
                html: str | None = resp.text
                bulletin_date = _bulletin_date_from_html(html) or _today_istanbul()
            else:
                html = await self._fetch_date(client, target_date)
                bulletin_date = target_date
            if html is None:
                return
            for price in self._parse_bulletin(html, bulletin_date):
                yield price

    async def _fetch_date(
        self,
        client: httpx.AsyncClient,
        target_date: date,
    ) -> str | None:
        """Fetch the bulletin HTML for a specific date.

        Args:
            client: The shared httpx client.
            target_date: Bulletin date to request.

        Returns:
            Response HTML on success, or ``None`` if the source returns an error
            (e.g. 500 for dates not in the select menu).
        """
        try:
            resp = await fetch_with_retry(
                client,
                "GET",
                URL,
                params={"tarih": target_date.strftime("%Y-%m-%d")},
            )
        except httpx.HTTPStatusError as exc:
            log.warning(
                "konya.bel.tr: fetch for %s failed with HTTP %s",
                target_date,
                exc.response.status_code,
            )
            return None
        except httpx.HTTPError as exc:
            log.warning("konya.bel.tr: fetch for %s failed: %s", target_date, exc)
            return None
        return resp.text

    @staticmethod
    def _parse_bulletin(html: str, bulletin_date: date) -> list[ProductPrice]:
        """Parse both section tables on the page into :class:`ProductPrice` rows.

        Args:
            html: Full page HTML for one bulletin date.
            bulletin_date: The bulletin date this HTML belongs to.

        Returns:
            A list of :class:`ProductPrice` records. Rows with no parseable price
            on either bound are silently dropped.
        """
        tree = HTMLParser(html)
        out: list[ProductPrice] = []
        for table in tree.css("table"):
            category = _table_category(table)
            if category is None:
                continue
            for row in _iter_data_rows(table):
                product_name, variety = _split_name_variety(row["product_name"])
                avg = _midpoint_decimal(row["price_low"], row["price_high"])
                if avg is None:
                    continue
                out.append(
                    ProductPrice(
                        city_name=CITY_NAME,
                        bulletin_date=bulletin_date,
                        product_name=product_name,
                        product_variety=variety,
                        product_category=category,
                        average_price=avg,
                        transaction_volume=None,
                        unit_name=row["unit_name"] or "Kg",
                    )
                )
        return out


# --- Module-level helpers (pure, easily testable) --------------------------


def _extract_available_dates(html: str) -> list[date]:
    """Read every ``<option value="YYYY-MM-DD">`` from the date ``<select>``.

    Args:
        html: Landing-page HTML.

    Returns:
        A list of unique bulletin dates known to the site. Empty list on parse
        failure (the caller logs and aborts in that case).
    """
    tree = HTMLParser(html)
    select = tree.css_first("select#tarih") or tree.css_first("select[name='tarih']")
    if select is None:
        return []
    found: set[date] = set()
    for opt in select.css("option"):
        value = (opt.attributes.get("value") or "").strip()
        if not value:
            continue
        try:
            found.add(datetime.strptime(value, "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(found)


def _bulletin_date_from_html(html: str) -> date | None:
    """Derive the bulletin date from the currently-selected option, if present.

    Args:
        html: Page HTML.

    Returns:
        The selected date, or ``None`` if no option carries the ``selected`` flag
        or the value isn't parseable.
    """
    m = re.search(r'<option\s+value="(\d{4}-\d{2}-\d{2})"\s+selected', html)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _table_category(table: Node) -> str | None:
    """Map a table's section header to its product_category, or ``None`` to skip.

    Args:
        table: A ``<table>`` :class:`selectolax.parser.Node`.

    Returns:
        ``"Sebze"`` for the vegetables table, ``"Meyve"`` for the fruits table,
        ``None`` for any other table on the page (decorative, the print modal, etc.).
    """
    th = table.css_first("thead th")
    if th is None:
        return None
    header = th.text(strip=True).upper()
    for needle, category in _SECTION_HEADERS.items():
        if needle in header:
            return category
    return None


def _iter_data_rows(table: Node) -> list[dict[str, str]]:
    """Extract data rows (skipping the section header and the column-label row).

    The Konya tables put the column labels in the first ``<tbody>`` row (as
    ``<td><strong>Ürün</strong></td>...``) rather than in ``<thead>``. We detect
    and skip that row by looking for the literal column-header tokens.

    Args:
        table: A ``<table>`` :class:`selectolax.parser.Node`.

    Returns:
        A list of dicts with keys ``product_name``, ``unit_name``, ``price_low``,
        ``price_high``.
    """
    rows: list[dict[str, str]] = []
    for tr in table.css("tbody tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 4:
            continue
        if _is_label_row(cells):
            continue
        rows.append(
            {
                "product_name": cells[0],
                "unit_name": cells[1],
                "price_low": cells[2],
                "price_high": cells[3],
            }
        )
    return rows


def _is_label_row(cells: list[str]) -> bool:
    """Detect the in-tbody column-label row (``Ürün / Birim / En Düşük / En Yüksek``).

    Args:
        cells: The text content of each ``<td>`` in the row.

    Returns:
        ``True`` if this row is the column-label row and should be skipped.
    """
    joined = "|".join(c.strip().upper() for c in cells[:4])
    return "ÜRÜN" in joined and "BIRIM" in joined.replace("İ", "I")


_VARIETY_RE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<variety>[^()]+)\)\s*$")


def _split_name_variety(raw: str) -> tuple[str, str | None]:
    """Split ``"ELMA (GRANNY SMİTH)"`` into ``("ELMA", "GRANNY SMİTH")``.

    Args:
        raw: The raw product-name cell. May or may not contain a parenthesized variety.

    Returns:
        A ``(product_name, variety_or_None)`` tuple. ``variety`` is ``None`` if the
        source cell has no parentheses or the variety is empty / ``"MUHTELİF"``
        (which means "miscellaneous / mixed" — keep it on the variety field
        because the source data does, but normalize to ``None`` if we ever need
        to: today we keep it verbatim).
    """
    s = raw.strip()
    m = _VARIETY_RE.match(s)
    if not m:
        return s, None
    name = m.group("name").strip()
    variety = m.group("variety").strip() or None
    return name, variety


_NBSP = "\xa0"
_DECIMAL_PARSE_ERRORS = (InvalidOperation, ValueError)


def _normalize_number(s: str) -> str:
    """Strip Turkish/European thousands separators and convert comma decimals to dot.

    Args:
        s: Raw numeric text from the page (e.g. ``"1.234,50"``, ``"32,40"``, ``"90"``).

    Returns:
        A string suitable for :class:`decimal.Decimal` (e.g. ``"1234.50"``).
    """
    return s.replace(_NBSP, "").replace(" ", "").replace(".", "").replace(",", ".")


def _to_decimal(s: str) -> Decimal | None:
    """Parse a number cell into a :class:`decimal.Decimal`.

    Args:
        s: Raw numeric text from the page.

    Returns:
        The parsed decimal, or ``None`` if the cell is empty or unparseable.
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(_normalize_number(s))
    except _DECIMAL_PARSE_ERRORS:
        return None


def _midpoint_decimal(low: str, high: str) -> Decimal | None:
    """Compute the midpoint of low/high price cells as a 4-place Decimal.

    Args:
        low: The ``En Düşük`` cell text.
        high: The ``En Yüksek`` cell text.

    Returns:
        ``(low + high) / 2`` if both parse; whichever single bound parses if the
        other is missing; ``None`` if neither parses. Quantized to 4 decimal places
        to match the ``NUMERIC(12,4)`` column.
    """
    lo = _to_decimal(low)
    hi = _to_decimal(high)
    if lo is None and hi is None:
        return None
    if lo is None:
        return hi
    if hi is None:
        return lo
    return ((lo + hi) / Decimal(2)).quantize(Decimal("0.0001"))


# --- DB / clock helpers ----------------------------------------------------


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_konya`` already has any row for ``d``.

    Args:
        session: An open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` when at least one row exists for that bulletin date. The backfill
        loop uses this to skip days that are already covered. ``False`` is returned
        if the table does not yet exist — the first ``upsert_prices`` call will
        create it.
    """
    try:
        res = await session.execute(
            text("SELECT 1 FROM prices_konya WHERE bulletin_date = :d LIMIT 1"),
            {"d": d},
        )
    except Exception:
        await session.rollback()
        return False
    return res.scalar() is not None


def _today_istanbul() -> date:
    """Today's date in Europe/Istanbul — the publisher's local time zone.

    Returns:
        The local calendar date in Konya's time zone.
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
        scraper = KonyaScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Konya scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`KonyaScraper.run`.
    """
    return await KonyaScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
