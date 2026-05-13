"""Scraper for the national bulletin at hal.gov.tr.

Each run backfills the last ``lookback_days`` (default 360) of national
prices. For every day in that window:

1. Skip if ``prices_national`` already has at least one row for that date.
2. Otherwise submit the page's date filter (``dateControlDate`` +
   ``btnGet`` / "Fiyat Bul"), walk every pagination postback, and UPSERT.

A scheduled run therefore stays cheap (1-2 missing days at most) while a
fresh database can catch up to a full year of history in one go.

Notes about the page:
- ASP.NET WebForms / SharePoint Form Web Part. Pagination + date filter are driven by
  ``__doPostBack`` against ``__VIEWSTATE`` / ``__EVENTVALIDATION`` hidden fields captured
  on the initial GET.
- The data table's id contains ``gvFiyatlar`` (ASP.NET GridView).
- The date filter is an ``<input type="text">`` named
  ``...$dateControl$dateControlDate`` in ``dd.mm.yyyy`` format; clicking
  ``btnGet`` ("Fiyat Bul") submits with the requested date.
- There is no city dropdown on this page — it is national/aggregate data.
  We store these rows under the synthetic city slug ``national``.
- SharePoint sometimes wraps postback responses in an UpdatePanel delta format
  (``len|type|id|html|...``). :func:`_extract_html` peels that wrapping off so the
  same :func:`_parse_table` works for both full-page and partial responses.
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

# City name used internally by the scraper. The slug derived from this string
# (via :func:`db.city_slug`) MUST match the seeded ``national`` row in the cities
# table — that's why we keep the English token here even though the UI shows
# the Turkish display name ``Ulusal`` from the cities table.
URL = "https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx"
NATIONAL_CITY_NAME = "National"

# Hidden fields ASP.NET sends with every postback.
_HIDDEN_FIELDS = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "__VIEWSTATEENCRYPTED",
    "__REQUESTDIGEST",
)

# Safety cap: hal.gov.tr never publishes more than a few dozen pages per day, so
# anything higher means we're stuck in a loop and should bail.
_MAX_PAGES = 200

# Default lookback window. Every scheduled run ensures the last `lookback_days`
# of bulletins are present in `prices_national` and re-scrapes the gaps.
_DEFAULT_LOOKBACK_DAYS = 360


class HalGovTrScraper:
    """Scraper for the national daily bulletin published at hal.gov.tr."""

    def __init__(
        self,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        page_sleep: float = 0.5,
    ) -> None:
        """Build the scraper.

        Args:
            lookback_days: How many days back from today to backfill. Days that
                already have at least one row in ``prices_national`` are
                skipped without an HTTP request.
            page_sleep: Seconds to wait between pagination postbacks so we
                don't hammer hal.gov.tr.
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
        """Fetch one day's bulletin and UPSERT it. Returns rows written (>=0)."""
        prices: list[ProductPrice] = []
        async for p in self.iter_prices(target):
            prices.append(p)
        if not prices:
            log.info("hal.gov.tr: no rows for %s (source empty for this date)", target)
            return 0
        wrote = await upsert_prices(session, prices)
        log.info("hal.gov.tr: %s wrote %d rows", target, wrote)
        return wrote

    # --- Core scrape loop --------------------------------------------------

    async def iter_prices(self, target_date: date | None = None) -> AsyncIterator[ProductPrice]:
        """Stream :class:`ProductPrice` records for one bulletin date.

        Args:
            target_date: The bulletin date to fetch. ``None`` means whatever
                hal.gov.tr renders by default (the latest available).

        Yields:
            One :class:`ProductPrice` per parsed data row, walking every page
            of that day's bulletin via ``Page$N`` postbacks. The row's
            ``bulletin_date`` is whatever the source rendered, which may be an
            earlier business day than ``target_date`` (the page sometimes
            falls back to the most recent published bulletin for non-business
            days).
        """
        async with http_client() as client:
            resp = await fetch_with_retry(client, "GET", URL)
            page_html = _extract_html(resp.text)

            if target_date is not None:
                filtered = await self._submit_date_filter(client, page_html, target_date)
                if filtered is None:
                    log.warning(
                        "hal.gov.tr: date filter unavailable, falling back to default page (%s)",
                        target_date,
                    )
                else:
                    page_html = filtered

            # Prefer the date filter input's own value — it's the only date on
            # the page guaranteed to be the bulletin date. The generic
            # ``dd.mm.yyyy`` regex matches incidental dates in the footer too,
            # so use it only as a last resort.
            bulletin_date = (
                _bulletin_date_from_filter(page_html)
                or self._extract_bulletin_date(page_html)
                or target_date
                or date.today()
            )

            # ASP.NET GridView only renders a sliding window of page numbers
            # (e.g. "1..10 ..."), so the total is re-discovered after every
            # navigation. We also stop early if a response yields zero rows.
            total_pages = _discover_total_pages(page_html)
            first_rows = list(_parse_table(page_html))
            log.info(
                "hal.gov.tr: bulletin_date=%s page=1 rows=%d visible_pages=%d",
                bulletin_date,
                len(first_rows),
                total_pages,
            )
            for row in first_rows:
                yield self._row_to_price(row, bulletin_date)

            page = 2
            while page <= _MAX_PAGES:
                next_html = await self._postback_page(client, page_html, page)
                if next_html is None:
                    log.warning("hal.gov.tr: page %d postback returned no usable response.", page)
                    break
                rows = list(_parse_table(next_html))
                # Re-extract the visible page window from the new response —
                # later pages reveal higher Page$N targets ("…11 12 13 …").
                discovered = _discover_total_pages(next_html)
                if discovered > total_pages:
                    total_pages = discovered
                log.info(
                    "hal.gov.tr: page=%d rows=%d visible_pages=%d",
                    page,
                    len(rows),
                    total_pages,
                )
                if not rows:
                    # Either we've walked past the last page or the postback
                    # returned a layout we cannot parse — stop in both cases.
                    break
                for row in rows:
                    yield self._row_to_price(row, bulletin_date)
                # Use the new response as the state seed for the next postback —
                # __VIEWSTATE/__EVENTVALIDATION rotate on every call.
                page_html = next_html
                page += 1
                if page > total_pages:
                    break
                await asyncio.sleep(self.page_sleep)

    # --- Form / postback ---------------------------------------------------

    async def _submit_date_filter(
        self,
        client: httpx.AsyncClient,
        initial_html: str,
        target_date: date,
    ) -> str | None:
        """Submit the page's date filter and return the filtered page HTML.

        Args:
            client: The shared httpx client.
            initial_html: HTML from the initial GET (carries the form's hidden
                state we need to echo back).
            target_date: Bulletin date to request, formatted ``dd.mm.yyyy``.

        Returns:
            The filtered page HTML, or ``None`` if the form prefix isn't
            discoverable (page layout change).
        """
        prefix = _extract_guid_prefix(initial_html)
        if prefix is None:
            return None
        form = _extract_hidden_fields(initial_html)
        form[f"{prefix}$dateControl$dateControlDate"] = target_date.strftime("%d.%m.%Y")
        # The "Fiyat Bul" button is a real submit, not __doPostBack — include
        # its name/value pair the way a browser submit would.
        form[f"{prefix}$btnGet"] = "Fiyat Bul"
        form["__EVENTTARGET"] = ""
        form["__EVENTARGUMENT"] = ""
        try:
            resp = await fetch_with_retry(client, "POST", URL, data=form)
        except httpx.HTTPStatusError as exc:
            log.warning("hal.gov.tr: date submit for %s failed: %s", target_date, exc)
            return None
        return _extract_html(resp.text)

    async def _postback_page(
        self,
        client: httpx.AsyncClient,
        prev_html: str,
        page_num: int,
    ) -> str | None:
        """Issue a ``Page$N`` postback for the GridView. Returns plain HTML or None."""
        grid_id = _extract_grid_id(prev_html)
        if grid_id is None:
            return None
        form = _extract_hidden_fields(prev_html)
        # Echo the date filter input value so pagination preserves it. The
        # __VIEWSTATE in hidden fields already encodes it server-side, but
        # carrying the visible value matches what a browser would do and
        # avoids any chance of losing the filter across postbacks.
        date_name, date_value = _extract_date_control(prev_html)
        if date_name and date_value:
            form[date_name] = date_value
        form["__EVENTTARGET"] = grid_id
        form["__EVENTARGUMENT"] = f"Page${page_num}"
        try:
            resp = await fetch_with_retry(
                client,
                "POST",
                URL,
                data=form,
                # Force a full-page postback. Setting X-MicrosoftAjax forces async
                # response; we explicitly do NOT send that header, but some
                # SharePoint pages still ship a delta — _extract_html handles both.
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        except httpx.HTTPStatusError as exc:
            log.warning("Pagination postback for page %d failed: %s", page_num, exc)
            return None
        return _extract_html(resp.text)

    # --- Bulletin date -----------------------------------------------------

    @staticmethod
    def _extract_bulletin_date(html: str) -> date | None:
        """Read the Turkish ``dd.mm.yyyy`` bulletin date rendered on the page."""
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", html)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(0), "%d.%m.%Y").date()
        except ValueError:
            return None

    @staticmethod
    def _row_to_price(row: dict[str, str], bulletin_date: date) -> ProductPrice:
        """Map a parsed table row to a :class:`ProductPrice`."""
        return ProductPrice(
            city_name=NATIONAL_CITY_NAME,
            bulletin_date=bulletin_date,
            product_name=row["product_name"],
            product_variety=row["product_variety"] or None,
            product_category=row["product_category"] or None,
            average_price=_to_decimal(row["average_price"]),
            transaction_volume=_to_int(row["transaction_volume"]),
            unit_name=row["unit_name"],
        )


# --- Module-level helpers (pure, easily testable) --------------------------


def _extract_guid_prefix(html: str) -> str | None:
    """Find the per-session ``ctl00$ctl37$g_<guid>`` form prefix.

    Args:
        html: Page HTML containing the date filter input.

    Returns:
        The prefix without any trailing leaf, or ``None`` if it isn't present.
    """
    m = re.search(r"(ctl00\$ctl37\$g_[0-9a-f_]+)\$dateControl\$dateControlDate", html)
    return m.group(1) if m else None


def _extract_date_control(html: str) -> tuple[str | None, str | None]:
    """Return the ``(name, value)`` of the page's date-filter ``<input>``.

    Args:
        html: Page HTML.

    Returns:
        A ``(name, value)`` tuple. Either or both may be ``None`` if the
        input is not present in the response.
    """
    m = re.search(
        r"<input[^>]*name=\"([^\"]+\$dateControl\$dateControlDate)\"[^>]*value=\"([^\"]*)\"",
        html,
    )
    if m:
        return m.group(1), m.group(2)
    return None, None


def _bulletin_date_from_filter(html: str) -> date | None:
    """Parse the bulletin date from the date filter input's ``value`` attribute.

    The page's footer also contains a ``dd.mm.yyyy`` copyright stamp that the
    generic regex would match — using the filter's ``value`` is the only
    reliable way to read what bulletin the page is showing.

    Args:
        html: Page HTML.

    Returns:
        The parsed date, or ``None`` if the input or its value is missing /
        unparseable.
    """
    _, value = _extract_date_control(html)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def _extract_hidden_fields(html: str) -> dict[str, str]:
    """Collect every known ASP.NET hidden field from an HTML or delta response."""
    out: dict[str, str] = {}
    # Try full HTML first.
    tree = HTMLParser(html)
    for inp in tree.css("input[type=hidden]"):
        name = inp.attributes.get("name")
        if name in _HIDDEN_FIELDS:
            out[name] = inp.attributes.get("value") or ""
    # Fallback: SharePoint delta format embeds them as
    # ``<len>|hiddenField|<name>|<value>``. Extract those too.
    for m in re.finditer(r"\|hiddenField\|([^|]+)\|([^|]*)", html):
        name, value = m.group(1), m.group(2)
        if name in _HIDDEN_FIELDS:
            out[name] = value
    return out


def _extract_grid_id(html: str) -> str | None:
    """Find the full unique id of the GridView (e.g. ``ctl00$ctl37$g_<guid>$gvFiyatlar``)."""
    m = re.search(r"(ctl00\$[^'\"]*gvFiyatlar)", html)
    return m.group(1) if m else None


def _extract_html(raw: str) -> str:
    """Return plain HTML from a response that may be in SharePoint async delta format.

    Args:
        raw: The raw response body.

    Returns:
        Plain HTML. For an async delta response, the largest ``updatePanel``
        segment is extracted (it contains the rerendered GridView); for a normal
        page it is returned unchanged.
    """
    # An async delta payload starts with a number-and-pipe sequence and contains
    # the literal ``|updatePanel|`` separator.
    if "|updatePanel|" not in raw:
        return raw
    # Crude but reliable: iterate pipe-delimited segments. The format is:
    #   <len>|<type>|<id>|<content>|...
    # We rebuild segments by length to handle any pipes inside the content.
    segments: list[str] = []
    i = 0
    while i < len(raw):
        # Find the pipe ending the length prefix.
        pipe = raw.find("|", i)
        if pipe == -1:
            break
        length_str = raw[i:pipe]
        if not length_str.isdigit():
            break
        length = int(length_str)
        # Skip "type|id|"
        head_end = raw.find("|", pipe + 1)
        head_end = raw.find("|", head_end + 1) if head_end != -1 else -1
        if head_end == -1:
            break
        content_start = head_end + 1
        content_end = content_start + length
        if content_end > len(raw):
            break
        segments.append(raw[pipe + 1 : content_end])
        # Move past the trailing pipe (if any).
        i = content_end + 1

    update_panels = [seg for seg in segments if seg.startswith("updatePanel|")]
    if not update_panels:
        return raw
    # Pick the segment with the most HTML payload — that's the GridView panel.
    longest = max(update_panels, key=len)
    # Strip the "updatePanel|<id>|" header — the content follows.
    parts = longest.split("|", 2)
    return parts[2] if len(parts) == 3 else raw


def _parse_table(html: str) -> list[dict[str, str]]:
    """Extract product rows from the gvFiyatlar GridView.

    Pagination rows (cells full of postback links or plain page numbers) are
    filtered out so they don't pollute the data.

    Args:
        html: Response HTML (full page or already-unwrapped delta segment).

    Returns:
        A list of dicts with keys product_name, product_variety, product_category,
        average_price, transaction_volume, unit_name.
    """
    tree = HTMLParser(html)
    table = tree.css_first("table[id*='gvFiyatlar']")
    if table is None:
        return []

    rows: list[dict[str, str]] = []
    for tr in table.css("tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 6:
            continue  # header or empty row
        if _looks_like_pager_row(tr, cells):
            continue
        if _is_garbage_name(cells[0]):
            # Real product names always contain letters; a numeric-only first
            # cell is paginator residue or a layout artifact.
            continue
        rows.append(
            {
                "product_name": cells[0],
                "product_variety": cells[1],
                "product_category": cells[2],
                "average_price": cells[3],
                "transaction_volume": cells[4],
                "unit_name": cells[5],
            }
        )
    return rows


def _is_garbage_name(value: str) -> bool:
    """A product name is garbage if it has no letters (purely numeric / punctuation)."""
    v = value.strip()
    if not v:
        return True
    # Must contain at least one alphabetic character. Catches "1", "12345678910",
    # "—", "(...)", etc.
    return not any(c.isalpha() for c in v)


def _looks_like_pager_row(_tr, cells: list[str]) -> bool:  # noqa: ANN001 — selectolax Node
    """Heuristic: a row is a paginator if every cell is a tiny number or link."""
    # Pagination rows in ASP.NET GridView have a single <td> with colspan that
    # wraps a series of <a>/<span> page selectors. After our text-strip above
    # those collapse to short numeric tokens like ``"1"``, ``"2"``, etc.
    # If every cell looks like a paginator token, treat it as a paginator row
    # regardless of whether the postback href is present (some renders strip JS).
    return all(_is_paginator_token(c) for c in cells)


def _is_paginator_token(value: str) -> bool:
    """A cell is paginator-ish if it's empty or a short(ish) digit-only string.

    Handles both per-cell page numbers (``"1"``, ``"42"``) and the case where
    several page links collapse into a single cell of concatenated digits
    (``"12345678910"``).
    """
    v = value.strip()
    if not v:
        return True
    return v.isdigit() and len(v) <= 30


def _discover_total_pages(html: str) -> int:
    """Infer the highest available page number from ``Page$N`` postback targets."""
    pages = {int(m.group(1)) for m in re.finditer(r"Page\$(\d+)", html)}
    if not pages:
        return 1
    return max(pages)


# --- Number parsing --------------------------------------------------------


_NBSP = "\xa0"
_DECIMAL_PARSE_ERRORS = (InvalidOperation, ValueError)


def _normalize_number(s: str) -> str:
    return s.replace(_NBSP, "").replace(" ", "").replace(".", "").replace(",", ".")


def _to_decimal(s: str) -> Decimal:
    try:
        return Decimal(_normalize_number(s))
    except _DECIMAL_PARSE_ERRORS:
        return Decimal(0)


def _to_int(s: str) -> int | None:
    cleaned = _normalize_number(s).split(".")[0]
    if not cleaned or not cleaned.lstrip("-").isdigit():
        return None
    return int(cleaned)


# --- DB / clock helpers ----------------------------------------------------


async def _has_data_for_date(session: AsyncSession, d: date) -> bool:
    """Return ``True`` if ``prices_national`` already has any row for ``d``.

    Args:
        session: An open async DB session.
        d: The bulletin date to check.

    Returns:
        ``True`` when at least one row exists for that bulletin date — the
        backfill loop uses this to skip days that are already covered.
    """
    res = await session.execute(
        text("SELECT 1 FROM prices_national WHERE bulletin_date = :d LIMIT 1"),
        {"d": d},
    )
    return res.scalar() is not None


def _today_istanbul() -> date:
    """Today's date in Europe/Istanbul — matches hal.gov.tr's bulletin clock.

    Returns:
        The local calendar date in the timezone hal.gov.tr publishes against.
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
        scraper = HalGovTrScraper()
        written = await scraper.run(session)
        log.info("Wrote %d rows.", written)


async def run(session: AsyncSession) -> int:
    """Run the national-bulletin scrape — module-level alias for the scheduler.

    Args:
        session: An open async DB session.

    Returns:
        Number of rows written by :meth:`HalGovTrScraper.run`.
    """
    return await HalGovTrScraper().run(session)


if __name__ == "__main__":
    asyncio.run(_main())
