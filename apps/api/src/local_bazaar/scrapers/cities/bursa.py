"""Scraper for the Bursa Metropolitan Municipality wholesale-market price bulletin.

The bulletin is published at
``https://www.bursa.bel.tr/hal_fiyatlari?sayfa=hal_fiyatlari&tarih=<dd.mm.yyyy>``.

Each run backfills the last ``lookback_days`` (default 160) of Bursa hal prices.
For every day in that window:

1. Skip if ``prices_bursa`` already has at least one row for that date.
2. Otherwise fetch ``?tarih=dd.mm.yyyy``, parse every category tab on the
   page, and UPSERT the rows.

Notes about the page:
- Server-rendered HTML (no JavaScript needed). A trivial ``GET`` is enough.
- The form is a plain HTML ``<form method="GET">`` with
  ``<input type="hidden" name="sayfa" value="hal_fiyatlari">`` and
  ``<input type="date" name="tarih">``.
- Despite the HTML5 ``type="date"`` input (which a browser would submit as
  ``yyyy-mm-dd``), the server normalises the parameter and always echoes the
  bulletin header as ``dd.mm.yyyy``. Empirically both ``dd.mm.yyyy`` and
  ``yyyy-mm-dd`` are accepted; we send ``dd.mm.yyyy`` because it matches the
  Turkish display format used on the page.
- The price table lives inside ``<table id="datatable">`` blocks, one per
  category tab (``#tab-2`` Meyve, ``#tab-3`` Sebze, ``#tab-4`` İthal, etc.).
  The tab label is read from the corresponding ``<a class="nav-link"
  href="#tab-N">…</a>`` link and stored as ``product_category``.
- There is **no pagination** — all categories render in one response.
- Columns are ``ÜRÜN`` (product), ``BR`` (unit), ``FİYAT`` (a price range like
  ``"8,00 - 80,00"`` followed by a Turkish-lira glyph). Bursa publishes a
  min/max range rather than a single average, and does **not** publish
  product variety, organic/conventional category, or transaction volume.
  We store the midpoint of the range as ``average_price`` and leave
  ``product_variety`` / ``transaction_volume`` as ``NULL``. The tab label
  (Meyve/Sebze/…) is the closest analogue to ``product_category`` and is
  written verbatim from the source.
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
    is_allowed,
    upsert_prices,
)

log = logging.getLogger(__name__)

URL = "https://www.bursa.bel.tr/hal_fiyatlari"
CITY_NAME = "Bursa"

# Default lookback window. Every scheduled run ensures the last
# ``lookback_days`` of Bursa bulletins are present in ``prices_bursa`` and
# re-scrapes the gaps.
_DEFAULT_LOOKBACK_DAYS = 160

# Safety cap on the per-day request loop in case the source starts redirecting.
_PAGE_SLEEP_DEFAULT = 0.5

# Unit normaliser: the source mixes "Kg.", "Kg", "kğ", "(kg)", "Adet" etc.
# We collapse the kilo variants to "Kg" and keep everything else verbatim.
_KG_PATTERN = re.compile(r"^\(?\s*k\s*[gğ]\.?\s*\)?$", re.IGNORECASE)


class BursaScraper:
    """Scraper for the Bursa Metropolitan Municipality hal-prices bulletin."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        page_sleep: float = _PAGE_SLEEP_DEFAULT,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill. Days that
                already have at least one row in ``prices_bursa`` are skipped
                without an HTTP request.
            page_sleep: Seconds to wait between per-day GETs so we don't hammer
                bursa.bel.tr.
        """
        self.lookback_days = lookback_days
        self.page_sleep = page_sleep

    async def run(self, session: AsyncSession) -> int:
        """Backfill every missing day in the last ``lookback_days``.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across all newly-scraped days. ``0`` is a valid
            return — it means every day in the lookback window already has
            data (or the source has none to give for the gaps), or that
            ``robots.txt`` disallows this run entirely.
        """
        if not await is_allowed(URL):
            log.warning("bursa: robots.txt disallows %s — skipping this run.", URL)
            return 0
        today = _today_istanbul()
        total = 0
        for offset in range(self.lookback_days):
            target = today - timedelta(days=offset)
            if await _has_data_for_date(session, target):
                continue
            wrote = await self._scrape_one_day(session, target)
            total += wrote
            # Polite spacing between dates, but only if we actually hit the network.
            await asyncio.sleep(self.page_sleep)
        return total

    async def _scrape_one_day(self, session: AsyncSession, target: date) -> int:
        """Fetch one day's bulletin and UPSERT it.

        Args:
            session: An open async DB session.
            target: The bulletin date to fetch.

        Returns:
            Number of rows written for this date (``0`` if the source had no
            bulletin published for it — Bursa skips weekends and holidays).
        """
        prices: list[ProductPrice] = []
        async for p in self.iter_prices(target):
            prices.append(p)
        if not prices:
            log.info("bursa: no rows for %s (source empty for this date)", target)
            return 0
        wrote = await upsert_prices(session, prices)
        log.info("bursa: %s wrote %d rows", target, wrote)
        return wrote

    async def iter_prices(self, target_date: date) -> AsyncIterator[ProductPrice]:
        """Stream :class:`ProductPrice` records for one bulletin date.

        Args:
            target_date: The bulletin date to fetch, formatted ``dd.mm.yyyy``
                in the query string.

        Yields:
            One :class:`ProductPrice` per parsed data row across every
            category tab on the page.
        """
        # The site's <input type="date"> implies ISO YYYY-MM-DD on the wire.
        # Empirically, dd.mm.yyyy renders an empty bulletin even though the
        # heading still echoes a dd.mm.yyyy display string. Always send ISO.
        params = {
            "sayfa": "hal_fiyatlari",
            "tarih": target_date.strftime("%Y-%m-%d"),
        }
        async with http_client() as client:
            resp = await fetch_with_retry(client, "GET", URL, params=params)
            html = resp.text

        bulletin_date = _bulletin_date_from_heading(html) or target_date
        if bulletin_date != target_date:
            # The site sometimes falls back to the most recent published
            # bulletin if you ask for a non-business day. Log it so the
            # caller knows what they actually got.
            log.info(
                "bursa: requested %s but page rendered bulletin %s",
                target_date,
                bulletin_date,
            )

        for row in _parse_tabs(html):
            price = _row_to_price(row, bulletin_date)
            if price is not None:
                yield price


# --- Module-level helpers (pure, easily testable) --------------------------


def _bulletin_date_from_heading(html: str) -> date | None:
    """Read the ``dd.mm.yyyy`` bulletin date echoed in the page heading.

    The page renders a heading like ``<h3>04.06.2026 Tarihli Hal Fiyatları</h3>``
    that mirrors the requested date back to the user.

    Args:
        html: Page HTML.

    Returns:
        The parsed bulletin date, or ``None`` if the heading is missing /
        malformed.
    """
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*Tarihli", html)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None


def _parse_tabs(html: str) -> list[dict[str, str]]:
    """Extract product rows from every ``#tab-N`` category pane.

    Each tab pane carries a ``<table id="datatable">`` with three columns
    (``ÜRÜN``, ``BR``, ``FİYAT``). The tab label (Meyve, Sebze, …) is taken
    from the matching ``<a href="#tab-N">`` nav link and attached to every row
    as ``category``.

    Args:
        html: Full page HTML.

    Returns:
        A list of dicts with keys ``product_name``, ``unit``, ``price_range``
        and ``category``. Rows with no parseable price range are dropped at
        the caller.
    """
    tree = HTMLParser(html)
    labels = _tab_labels(tree)
    # Allow Meyve, Sebze, and any "İthal" produce tabs; skip seafood tabs
    # like "Pelajik" / "Dip" / "İç Su" / "Su Ürünleri".
    _allowed_categories = {"Meyve", "Sebze"}
    _allowed_substrings = ("İthal", "ithal", "i̇thal")

    rows: list[dict[str, str]] = []
    for pane in tree.css("div.tab-pane"):
        pane_id = pane.attributes.get("id") or ""
        category = labels.get(pane_id, "")
        if category not in _allowed_categories and not any(
            s in category for s in _allowed_substrings
        ):
            continue
        table = pane.css_first("table#datatable")
        if table is None:
            continue
        tbody = table.css_first("tbody")
        if tbody is None:
            continue
        for tr in tbody.css("tr"):
            cells = [c.text(strip=True) for c in tr.css("td")]
            if len(cells) < 3:
                continue
            product_name = cells[0].strip()
            unit = cells[1].strip()
            price_range = cells[2].strip()
            if not product_name or not price_range:
                continue
            rows.append(
                {
                    "product_name": product_name,
                    "unit": unit,
                    "price_range": price_range,
                    "category": category,
                }
            )
    return rows


def _tab_labels(tree: HTMLParser) -> dict[str, str]:
    """Map each ``tab-N`` pane id to its human-readable nav label.

    Args:
        tree: A parsed :class:`selectolax.parser.HTMLParser` for the page.

    Returns:
        A dict like ``{"tab-2": "Meyve", "tab-3": "Sebze", ...}``. Panes whose
        nav link is missing fall back to the empty string at the call site.
    """
    labels: dict[str, str] = {}
    for link in tree.css("a.nav-link[href^='#tab-']"):
        href = link.attributes.get("href") or ""
        pane_id = href.lstrip("#")
        if pane_id:
            labels[pane_id] = link.text(strip=True)
    return labels


def _row_to_price(row: dict[str, str], bulletin_date: date) -> ProductPrice | None:
    """Map a parsed table row to a :class:`ProductPrice`.

    Args:
        row: One dict produced by :func:`_parse_tabs`.
        bulletin_date: The bulletin date to stamp on the record.

    Returns:
        A :class:`ProductPrice`, or ``None`` if the price range could not be
        parsed (defensive guard against layout changes).
    """
    price = _midpoint(row["price_range"])
    if price is None:
        return None
    return ProductPrice(
        city_name=CITY_NAME,
        bulletin_date=bulletin_date,
        product_name=row["product_name"],
        product_variety=None,
        product_category=row["category"] or None,
        average_price=price,
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit"]),
    )


# --- Number / unit parsing -------------------------------------------------


_NBSP = "\xa0"
_DECIMAL_PARSE_ERRORS = (InvalidOperation, ValueError)
# Captures one or two Turkish decimals separated by "-" (e.g. "8,00 - 80,00"
# or "25,00"). The trailing TRY glyph (``₺``) and stray whitespace are
# tolerated by the surrounding regex.
_RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:-\s*(\d+(?:[.,]\d+)?))?")


def _normalize_number(s: str) -> str:
    """Strip Turkish thousands separators and convert decimal comma to dot.

    Args:
        s: A raw numeric token like ``"1.234,56"`` or ``"8,00"``.

    Returns:
        A string parseable by :class:`decimal.Decimal`.
    """
    return s.replace(_NBSP, "").replace(" ", "").replace(".", "").replace(",", ".")


def _to_decimal(s: str) -> Decimal | None:
    """Parse one normalised numeric token into a :class:`Decimal`.

    Args:
        s: A pre-normalised numeric string (dot decimal, no thousands sep).

    Returns:
        The parsed :class:`Decimal`, or ``None`` if the input is not numeric.
    """
    try:
        return Decimal(s)
    except _DECIMAL_PARSE_ERRORS:
        return None


def _midpoint(price_range: str) -> Decimal | None:
    """Compute the midpoint of a Bursa price range like ``"8,00 - 80,00"``.

    Bursa publishes a min–max range rather than a single average price; we
    store the midpoint as ``average_price`` so the field stays comparable
    across cities. A single-value range (e.g. ``"25,00"``) is returned as-is.

    Args:
        price_range: The raw ``FİYAT`` cell content. May contain a trailing
            currency glyph or whitespace.

    Returns:
        The midpoint as a :class:`Decimal` quantised to 4 fractional digits,
        or ``None`` if no numeric value could be extracted.
    """
    m = _RANGE_RE.search(price_range)
    if not m:
        return None
    low = _to_decimal(_normalize_number(m.group(1)))
    if low is None:
        return None
    high_raw = m.group(2)
    if high_raw is None:
        mid = low
    else:
        high = _to_decimal(_normalize_number(high_raw))
        mid = low if high is None else (low + high) / Decimal(2)
    return mid.quantize(Decimal("0.0001"))


def _normalize_unit(unit: str) -> str:
    """Collapse the source's many spellings of "kilogram" to ``"Kg"``.

    The Bursa page mixes ``"Kg."``, ``"Kg"``, ``"kğ"``, ``"(kg)"`` and bare
    ``"kg"`` across rows. We normalise all of these to ``"Kg"`` so per-product
    history queries don't fragment along punctuation. Everything else (e.g.
    ``"Adet"``) is stripped of trailing punctuation and otherwise preserved.

    Args:
        unit: The raw ``BR`` cell content.

    Returns:
        The cleaned unit string, defaulting to ``"Kg"`` on an empty input.
    """
    cleaned = unit.strip().strip(".").strip()
    if not cleaned:
        return "Kg"
    if _KG_PATTERN.match(cleaned):
        return "Kg"
    return cleaned


# --- DB / clock helpers ----------------------------------------------------


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_bursa`` already has any row for ``d``.

    The table may not yet exist on a fresh database — :func:`upsert_prices`
    creates it on first write via ``db.ensure_city_table``. Until then we
    treat "table missing" as "no data" so the backfill loop runs.

    Args:
        session: An open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` when at least one row exists for that bulletin date,
        ``False`` otherwise (including when the table doesn't exist yet).
    """
    res = await session.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'prices_bursa'"
        )
    )
    if res.scalar() is None:
        return False
    res = await session.execute(
        text("SELECT 1 FROM prices_bursa WHERE bulletin_date = :d LIMIT 1"),
        {"d": d},
    )
    return res.scalar() is not None


def _today_istanbul() -> date:
    """Today's date in Europe/Istanbul — matches the bursa.bel.tr clock.

    Returns:
        The local calendar date in Turkey, which is the timezone Bursa
        publishes against.
    """
    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


# --- CLI entrypoint --------------------------------------------------------


async def _main() -> None:
    """Run the Bursa scraper standalone — useful for one-off scrapes and debugging."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = BursaScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Bursa scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`BursaScraper.run`.
    """
    return await BursaScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
