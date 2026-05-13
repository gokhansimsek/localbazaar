"""Scraper for hal.gov.tr/Sayfalar/Pazar-Yerleri.aspx (Pazar Yerleri / bazaar locations).

The page is an ASP.NET WebForms search form. Three selects + a submit button:

1. ``ddlIl``         — province; selecting one fires an ``__doPostBack`` that
   repopulates ``ddlIlce``.
2. ``ddlIlce``       — district.
3. ``ddlPazarTuru``  — market type (``0`` = Tümü, ``9`` = Semt Pazarı, ``10`` = Üretici Pazarı).
4. ``BtnAra``        — submit ("Pazar Yeri Bul").

Element ids are prefixed with a per-session GUID such as
``ctl00$ctl37$g_<guid>$ddlIl``; :func:`_extract_guid_prefix` discovers it from
the initial GET.

Result rows live in a GridView whose id contains ``gvListe``. Columns are:
``Pazar Adı | Türü | Adres | İl | İlçe | Semt | Kuruluş Günleri``.

Two source quirks the scraper normalizes:

- Market names sometimes carry parenthetical "section" suffixes ("MURATBEY SEMT
  PAZARI (BALIK BÖLÜMÜ)"). We strip everything in parens so all sections roll up
  into one logical market (``MURATBEY SEMT PAZARI``).
- "Kuruluş Günleri" mixes short and full forms ("Pzt,Pazar", "Salı,Çrş"). We
  expand every token to its full Turkish day name.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from local_bazaar.db import city_slug
from local_bazaar.models import District, Market, MarketType, Province
from local_bazaar.scrapers.base import fetch_with_retry, http_client

log = logging.getLogger(__name__)

URL = "https://www.hal.gov.tr/Sayfalar/Pazar-Yerleri.aspx"

# Hidden ASP.NET fields that every postback must echo back.
_HIDDEN_FIELDS = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "__VIEWSTATEENCRYPTED",
    "__REQUESTDIGEST",
)

# (label-as-shown-on-the-page, ddlPazarTuru option value, MarketType enum) tuples.
_MARKET_TYPES: tuple[tuple[str, str, MarketType], ...] = (
    ("Semt Pazarı", "9", MarketType.SEMT_PAZARI),
    ("Üretici Pazarı", "10", MarketType.URETICI_PAZARI),
)

# Map of every short / full / case-variant token seen on the source to the full
# Turkish day name. The page is inconsistent — some districts use "Pzt" while
# others spell out "Pazar". Anything not in the map is kept verbatim.
_DAY_LOOKUP: dict[str, str] = {
    "pzt": "Pazartesi",
    "pts": "Pazartesi",
    "pazartesi": "Pazartesi",
    "sal": "Salı",
    "salı": "Salı",
    "sali": "Salı",
    "çar": "Çarşamba",
    "çrş": "Çarşamba",
    "carsamba": "Çarşamba",
    "çarşamba": "Çarşamba",
    "per": "Perşembe",
    "prş": "Perşembe",
    "persembe": "Perşembe",
    "perşembe": "Perşembe",
    "cum": "Cuma",
    "cuma": "Cuma",
    "cmt": "Cumartesi",
    "cumartesi": "Cumartesi",
    "paz": "Pazar",
    "pazar": "Pazar",
}


def _control_name(prefix: str, leaf: str) -> str:
    return f"{prefix}${leaf}"


def _extract_hidden_fields(html: str) -> dict[str, str]:
    """Collect every known ASP.NET hidden field from an HTML response."""
    tree = HTMLParser(html)
    out: dict[str, str] = {}
    for inp in tree.css("input[type=hidden]"):
        name = inp.attributes.get("name")
        if name in _HIDDEN_FIELDS:
            out[name] = inp.attributes.get("value") or ""
    return out


def _extract_guid_prefix(html: str) -> str | None:
    """Discover the per-session ``ctl00$ctl37$g_<guid>`` prefix used by the form."""
    m = re.search(r"(ctl00\$ctl37\$g_[0-9a-f_]+)\$ddlIl\"", html)
    return m.group(1) if m else None


def _extract_select_options(html: str, select_id_suffix: str) -> list[tuple[str, str]]:
    """Return ``[(value, label)]`` for all ``<option>`` elements in a select.

    Args:
        html: Page HTML.
        select_id_suffix: A unique suffix on the select id (e.g. ``"ddlIl"``).

    Returns:
        Cleaned ``(value, label)`` pairs (placeholder options removed).
    """
    pattern = re.compile(
        rf"<select[^>]*id=\"[^\"]*{re.escape(select_id_suffix)}\"[^>]*>(.*?)</select>",
        re.DOTALL,
    )
    m = pattern.search(html)
    if not m:
        return []
    options = re.findall(
        r"<option[^>]*value=\"([^\"]*)\"[^>]*>([^<]*)</option>",
        m.group(1),
    )
    placeholders = {"Tümü", "Seçiniz", "İl Seçiniz", "İlçe Seçiniz", "Tür Seçiniz"}
    cleaned: list[tuple[str, str]] = []
    for value, label in options:
        value = value.strip()
        label = _decode_entities(label).strip()
        if not value or value == "0" or label in placeholders:
            continue
        cleaned.append((value, label))
    return cleaned


def _decode_entities(s: str) -> str:
    """Decode the small set of numeric/named HTML entities the source uses."""
    import html as _html

    return _html.unescape(s)


def _normalize_market_name(raw: str) -> str:
    """Strip parens, expand abbreviations, and Title-Case.

    ``"MURATBEY SEMT PAZARI (BALIK BÖLÜMÜ)"`` → ``"Muratbey Semt Pazarı"``.
    ``"MURATBEY KPY"``                          → ``"Muratbey Kapalı Pazar Yeri"``.

    Steps (in order, since later steps depend on earlier ones):
    1. Strip everything in parentheses, repeated to handle chained suffixes.
    2. Expand whole-word abbreviations like ``KPY``.
    3. Collapse whitespace and Title-Case the result.
    """
    name = _decode_entities(raw)
    prev = None
    while name != prev:
        prev = name
        name = re.sub(r"\s*\([^()]*\)\s*", " ", name)
    name = _expand_abbreviations(name)
    name = re.sub(r"\s+", " ", name).strip()
    return to_title_case_tr(name)


# Whole-word abbreviations seen on hal.gov.tr market names. Keys are case-folded
# (uppercase) for a single-direction case-insensitive match; values are the
# canonical full forms in Title Case (the final to_title_case_tr pass keeps the
# casing consistent regardless).
_ABBREVIATIONS: dict[str, str] = {
    "KPY": "Kapalı Pazar Yeri",
}


def _expand_abbreviations(text: str) -> str:
    """Replace each known abbreviation token with its full form (whole-word match)."""

    def _swap(match: re.Match[str]) -> str:
        token = match.group(0).upper()
        return _ABBREVIATIONS.get(token, match.group(0))

    if not _ABBREVIATIONS:
        return text
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in _ABBREVIATIONS) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(_swap, text)


def to_title_case_tr(text: str) -> str:
    r"""Turkish-aware Title Case (handles the ı/İ/i/I family correctly).

    Each ``\w+`` run is treated as a word: the first character is uppercased
    with Turkish rules, the rest is lowercased. Punctuation between word runs
    (``.``, ``,``, ``-``, etc.) is preserved verbatim so addresses like
    ``"B.Evleri"`` round-trip cleanly.

    Args:
        text: Input string in any case.

    Returns:
        Title-cased copy of ``text``.
    """
    if not text:
        return text
    return re.sub(r"\w+", lambda m: _cap_word_tr(m.group(0)), text)


def _cap_word_tr(word: str) -> str:
    # Lowercase the whole word with Turkish I rules, then uppercase the first letter.
    lowered = word.replace("I", "ı").replace("İ", "i").lower()
    if not lowered:
        return lowered
    first = lowered[0]
    first_up = "İ" if first == "i" else ("I" if first == "ı" else first.upper())
    return first_up + lowered[1:]


def _normalize_days(raw: str) -> str | None:
    """Expand a comma-separated list of short/long Turkish day names.

    ``"Pzt,Pazar"`` → ``"Pazartesi,Pazar"``. Unknown tokens are kept verbatim
    (so the source can't silently lose information when it ships a new spelling).
    """
    text = _decode_entities(raw).strip()
    if not text:
        return None
    parts: list[str] = []
    for raw_token in re.split(r"[,/;|]+", text):
        token = raw_token.strip()
        if not token:
            continue
        key = token.lower()
        parts.append(_DAY_LOOKUP.get(key, token))
    return ",".join(parts) if parts else None


def _parse_markets(html: str) -> list[dict[str, str]]:
    """Extract the result rows from the gvListe GridView.

    Returns:
        A list of dicts keyed by ``name`` (raw), ``type_label``, ``address``,
        ``province``, ``district``, ``neighborhood``, ``days_raw``.
    """
    tree = HTMLParser(html)
    table = tree.css_first("table[id*='gvListe']")
    if table is None:
        return []

    rows: list[dict[str, str]] = []
    for tr in table.css("tr"):
        cells = [c.text(strip=True) for c in tr.css("td")]
        if len(cells) < 7:
            continue  # header / spacer
        rows.append(
            {
                "name": _decode_entities(cells[0]),
                "type_label": _decode_entities(cells[1]),
                "address": _decode_entities(cells[2]),
                "province": _decode_entities(cells[3]),
                "district": _decode_entities(cells[4]),
                "neighborhood": _decode_entities(cells[5]),
                "days_raw": cells[6],
            }
        )
    return rows


def _market_type_from_label(label: str) -> MarketType | None:
    for source_label, _, enum_val in _MARKET_TYPES:
        if source_label == label.strip():
            return enum_val
    return None


# --- DB upserts ----------------------------------------------------------


async def _get_or_create_province(session: AsyncSession, name: str) -> Province:
    pretty = to_title_case_tr(name)
    slug = city_slug(pretty)
    province = (
        await session.execute(select(Province).where(col(Province.slug) == slug))
    ).scalar_one_or_none()
    if province is None:
        province = Province(slug=slug, name=pretty)
        session.add(province)
        await session.flush()
    elif province.name != pretty:
        province.name = pretty
    return province


async def _get_or_create_district(session: AsyncSession, province: Province, name: str) -> District:
    pretty = to_title_case_tr(name)
    slug = city_slug(pretty)
    assert province.id is not None, "province must be flushed before creating districts"
    district = (
        await session.execute(
            select(District).where(
                col(District.province_id) == province.id, col(District.slug) == slug
            )
        )
    ).scalar_one_or_none()
    if district is None:
        district = District(province_id=province.id, slug=slug, name=pretty)
        session.add(district)
        await session.flush()
    elif district.name != pretty:
        district.name = pretty
    return district


def _normalize_address(raw: str | None) -> str | None:
    """Decode entities, strip whitespace, and Turkish-aware title-case an address.

    The ``markets.address`` column is the canonical store for hal.gov.tr's raw
    address text. Geocoding lives in a separate script (``scripts/geocode_markets.py``);
    this scraper never calls the Google API. Always normalize here so every
    row that touches the DB is in consistent Title Case.

    Args:
        raw: Raw address text as scraped, may contain HTML entities or be ``None``.

    Returns:
        Title-cased address, or ``None`` if the input was empty / missing.
    """
    if not raw:
        return None
    cleaned = _decode_entities(raw).strip()
    if not cleaned:
        return None
    return to_title_case_tr(cleaned)


async def _upsert_markets(
    session: AsyncSession,
    district: District,
    market_type: MarketType,
    rows: Iterable[dict[str, str]],
) -> int:
    """Insert (or refresh) markets, collapsing parenthetical variants by name."""
    written = 0
    seen_in_batch: set[str] = set()
    assert district.id is not None, "district must be flushed before creating markets"
    for row in rows:
        normalized_name = _normalize_market_name(row["name"])
        if not normalized_name or normalized_name in seen_in_batch:
            continue
        seen_in_batch.add(normalized_name)

        days = _normalize_days(row["days_raw"])
        address = _normalize_address(row.get("address"))

        existing = (
            await session.execute(
                select(Market).where(
                    col(Market.district_id) == district.id,
                    col(Market.market_type) == market_type,
                    col(Market.name) == normalized_name,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Market(
                    district_id=district.id,
                    market_type=market_type,
                    name=normalized_name,
                    address=address,
                    day_of_week=days,
                )
            )
            written += 1
        else:
            # Always store a title-cased address. If the scrape didn't return
            # one, re-normalize whatever's in the row so the invariant holds
            # even for legacy data inserted before this normalization existed.
            if address:
                existing.address = address
            elif existing.address:
                existing.address = _normalize_address(existing.address)
            existing.day_of_week = days or existing.day_of_week
    await session.commit()
    return written


# --- Scraper -------------------------------------------------------------


class BazaarLocationsScraper:
    """End-to-end crawl of hal.gov.tr/Sayfalar/Pazar-Yerleri.aspx."""

    def __init__(self, *, page_sleep: float = 0.4) -> None:
        """Build the scraper.

        Args:
            page_sleep: Seconds to wait between province / district / type
                postbacks. The source rate-limits aggressively; keep > 0.
        """
        self.page_sleep = page_sleep

    async def run(self, session: AsyncSession) -> int:
        """Crawl every province × district × market-type and UPSERT into ``markets``.

        Args:
            session: An open async DB session.

        Returns:
            Total number of market rows written (or refreshed) in this run.
        """
        total = 0
        async with http_client() as client:
            initial = await fetch_with_retry(client, "GET", URL)
            html = initial.text
            prefix = _extract_guid_prefix(html)
            if prefix is None:
                log.warning("bazaar-locations: could not discover form prefix; aborting.")
                return 0

            provinces = _extract_select_options(html, "ddlIl")
            log.info("bazaar-locations: discovered %d provinces", len(provinces))

            for prov_value, prov_label in provinces:
                try:
                    province_html = await self._select_province(client, html, prefix, prov_value)
                except httpx.HTTPError as exc:
                    log.warning("province %s postback failed: %s", prov_label, exc)
                    continue

                province = await _get_or_create_province(session, prov_label)
                districts = _extract_select_options(province_html, "ddlIlce")
                log.info("bazaar-locations: province=%s districts=%d", prov_label, len(districts))

                for dist_value, dist_label in districts:
                    district = await _get_or_create_district(session, province, dist_label)
                    for type_label, type_code, type_enum in _MARKET_TYPES:
                        try:
                            result_html = await self._submit_search(
                                client,
                                province_html,
                                prefix,
                                prov_value,
                                dist_value,
                                type_code,
                            )
                        except httpx.HTTPError as exc:
                            log.warning(
                                "submit %s/%s/%s failed: %s",
                                prov_label,
                                dist_label,
                                type_label,
                                exc,
                            )
                            continue

                        rows = _parse_markets(result_html)
                        # Filter to rows whose type label actually matches what we asked
                        # for (the source sometimes returns a Tümü-style superset).
                        rows = [
                            r for r in rows if _market_type_from_label(r["type_label"]) == type_enum
                        ]
                        if rows:
                            wrote = await _upsert_markets(session, district, type_enum, rows)
                            total += wrote
                            log.info(
                                "bazaar-locations: %s/%s/%s rows=%d wrote=%d",
                                prov_label,
                                dist_label,
                                type_label,
                                len(rows),
                                wrote,
                            )
                        await asyncio.sleep(self.page_sleep)

                await asyncio.sleep(self.page_sleep)

        log.info("bazaar-locations: crawl complete — wrote %d rows total.", total)
        return total

    async def _select_province(
        self,
        client: httpx.AsyncClient,
        prev_html: str,
        prefix: str,
        prov_value: str,
    ) -> str:
        form = _extract_hidden_fields(prev_html)
        form[_control_name(prefix, "ddlIl")] = prov_value
        form["__EVENTTARGET"] = _control_name(prefix, "ddlIl")
        form["__EVENTARGUMENT"] = ""
        resp = await fetch_with_retry(client, "POST", URL, data=form)
        return resp.text

    async def _submit_search(
        self,
        client: httpx.AsyncClient,
        prev_html: str,
        prefix: str,
        prov_value: str,
        dist_value: str,
        type_code: str,
    ) -> str:
        form = _extract_hidden_fields(prev_html)
        form[_control_name(prefix, "ddlIl")] = prov_value
        form[_control_name(prefix, "ddlIlce")] = dist_value
        form[_control_name(prefix, "ddlPazarTuru")] = type_code
        form[_control_name(prefix, "BtnAra")] = "Pazar Yeri Bul"
        resp = await fetch_with_retry(client, "POST", URL, data=form)
        return resp.text


# --- Module-level entrypoints --------------------------------------------


async def run(session: AsyncSession) -> int:
    """Run the markets crawl (module-level alias used by the scheduler).

    Args:
        session: An open async DB session.

    Returns:
        Number of market rows written by :meth:`BazaarLocationsScraper.run`.
    """
    return await BazaarLocationsScraper().run(session)


async def _main() -> None:
    """CLI entrypoint for one-off scrapes (``python -m ...``)."""
    from local_bazaar.db import SessionLocal

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    async with SessionLocal() as session:
        written = await run(session)
        log.info("Wrote %d markets.", written)


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = [
    "URL",
    "_DAY_LOOKUP",
    "BazaarLocationsScraper",
    "_extract_guid_prefix",
    "_extract_hidden_fields",
    "_extract_select_options",
    "_normalize_days",
    "_normalize_market_name",
    "_parse_markets",
    "run",
]
