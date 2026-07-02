"""Scraper for the Antalya Büyükşehir Belediyesi hal daily bulletin.

Source: https://www.antalya.bel.tr/tr/halden-gunluk-fiyatlar

The page is a Vue 3 SPA. The visible ``<table id="haldengunlukfiyatlartable">``
renders only ``{{item.urun_adi}}`` placeholders in raw HTML; the data is
fetched after page load by jQuery against an endpoint hidden in obfuscated
JavaScript. Plain ``httpx`` cannot extract anything — we drive a headless
Chromium via Playwright and read the DOM after Vue hydrates.

URL convention (taken from the page's own datepicker behavior)::

    ?fiyattarih=DD.MM.YYYY

Loading the URL with no parameters gives the most-recent published bulletin.
For backfill we navigate to ``?fiyattarih=DD.MM.YYYY`` once per missing day.
The page renders ``En Düşük`` / ``En Yüksek`` / ``Ortalama`` columns — we use
the source-published ``Ortalama`` directly as ``average_price``.

Operationally: Chromium must be available in the image. Playwright is an
optional extra in :file:`pyproject.toml`; install with::

    uv sync --extra playwright
    playwright install chromium

The project Dockerfile already wires both steps for cluster runs.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.scrapers.base import ProductPrice, upsert_prices

log = logging.getLogger(__name__)

CITY_NAME = "Antalya"
_SLUG = "antalya"
_URL = "https://www.antalya.bel.tr/tr/halden-gunluk-fiyatlar"
_DEFAULT_LOOKBACK_DAYS = 160
_PAGE_TIMEOUT_MS = 30_000
_TABLE_SELECTOR = "#haldengunlukfiyatlartable"
_ROW_SELECTOR = f"{_TABLE_SELECTOR} tbody tr"
_DAY_SLEEP = 0.6


class AntalyaScraper:
    """Scrape Antalya's hal daily bulletins via a headless Chromium."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        day_sleep: float = _DAY_SLEEP,
        headless: bool = True,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill.
            day_sleep: Pause between sequential day fetches so we don't hammer
                the source.
            headless: Run Chromium headless. Override to ``False`` only when
                debugging locally.
        """
        self.lookback_days = lookback_days
        self.day_sleep = day_sleep
        self.headless = headless

    async def run(self, session: AsyncSession) -> int:
        """Backfill every missing bulletin in the lookback window.

        Args:
            session: An open async DB session.

        Returns:
            Total rows written across newly-scraped days.
        """
        # Import lazily so importing the module doesn't pull Playwright into
        # the API process at startup. The scheduler imports this module on
        # demand for each city scrape; missing Playwright surfaces as an
        # ImportError logged below rather than crashing the scheduler.
        try:
            async_playwright = importlib.import_module("playwright.async_api").async_playwright
        except ImportError as exc:
            log.warning(
                "antalya: playwright is not installed (%s) — skipping. "
                "Install with `uv sync --extra playwright && playwright install chromium`.",
                exc,
            )
            return 0

        today = _today_istanbul()
        total = 0
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            try:
                context = await browser.new_context(
                    locale="tr-TR",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                for offset in range(self.lookback_days):
                    target = today - timedelta(days=offset)
                    if await _has_data_for_date(session, target):
                        continue
                    prices: list[ProductPrice] = []
                    async for pr in self._iter_day(page, target):
                        prices.append(pr)
                    if prices:
                        wrote = await upsert_prices(session, prices)
                        total += wrote
                        log.info("antalya: %s wrote %d rows", target, wrote)
                    else:
                        log.info("antalya: %s no rows (page empty)", target)
                    if offset < self.lookback_days - 1:
                        await asyncio.sleep(self.day_sleep)
            finally:
                await browser.close()
        return total

    async def _iter_day(self, page, target: date) -> AsyncIterator[ProductPrice]:  # noqa: ANN001
        """Navigate to one bulletin date and yield :class:`ProductPrice` rows.

        Args:
            page: An open Playwright :class:`Page`.
            target: Bulletin date to fetch.

        Yields:
            One :class:`ProductPrice` per row rendered in the result table.
        """
        url = f"{_URL}?fiyattarih={target.strftime('%d.%m.%Y')}"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS)
            # Vue hydrates the table after the AJAX call resolves. We wait for
            # the first <tr> in tbody — that's enough to confirm hydration
            # finished without depending on any specific row count.
            try:
                await page.wait_for_selector(
                    _ROW_SELECTOR, timeout=_PAGE_TIMEOUT_MS, state="attached"
                )
            except Exception:
                # No rows for this date (weekend / holiday) — return an empty result.
                return
            html = await page.content()
        except Exception as exc:
            log.warning("antalya: page load for %s failed: %s", target, exc)
            return
        for row in _parse_table(html):
            yield _row_to_price(row, target)


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract product rows from the hydrated ``haldengunlukfiyatlartable``.

    The Vue template binds five ``<td>`` cells per row in document order:

    1. an ``<img>`` thumbnail (hidden, empty text)
    2. product name (``{{item.urun_adi}}``)
    3. lowest price (``{{item.en_dusuk_fiyat}}``)
    4. highest price (``{{item.en_yuksek_fiyat}}``)
    5. unit (``{{item.birim_adi_combobox.birim_adi}}``)

    Rows without the full 5-cell layout are skipped.

    Args:
        html: Fully-rendered page HTML (after Vue hydration).

    Returns:
        A list of dicts with keys product, unit, low, high.
    """
    tree = HTMLParser(html)
    table = tree.css_first(_TABLE_SELECTOR)
    if table is None:
        return []
    rows: list[dict[str, str]] = []
    for tr in table.css("tbody tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 5:
            continue
        product = cells[1].strip()
        if not product:
            continue
        rows.append(
            {
                "product": product,
                "unit": cells[4].strip(),
                "low": cells[2],
                "high": cells[3],
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
    low = _to_decimal(row["low"])
    high = _to_decimal(row["high"])
    average = ((low + high) / Decimal(2)).quantize(Decimal("0.0001"))
    return ProductPrice(
        city_name=CITY_NAME,
        bulletin_date=bulletin_date,
        product_name=row["product"].strip(),
        product_variety=None,
        product_category=None,
        average_price=average,
        transaction_volume=None,
        unit_name=_normalize_unit(row["unit"]),
    )


def _normalize_unit(unit: str) -> str:
    """Normalize the source's birim cell to ``Kg`` / ``Adet``.

    Args:
        unit: Raw birim text.

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
        s: Raw cell text (``"32,40 TL"``, ``"1.234,56 ₺"``, ``"\xa0"``, ...).

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
    """Return ``True`` if ``prices_antalya`` already has any row for ``d``.

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
    """Run the Antalya scraper standalone — useful for one-off scrapes."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        scraper = AntalyaScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the Antalya scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`AntalyaScraper.run`.
    """
    return await AntalyaScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
