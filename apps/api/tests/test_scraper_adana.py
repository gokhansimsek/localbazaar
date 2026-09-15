"""Unit tests for the Adana Büyükşehir Belediyesi hal-prices scraper.

Adana is the two-layer scraper: a listing page enumerates ``(date, detail_id)``
pairs, and each detail page carries the actual price tables. These tests cover
listing-page parsing, detail-header date extraction, detail-table parsing,
the dot-decimal-separator + Turkish title-casing row mapping, and an
end-to-end respx-mocked run through ``_discover_entries`` + ``_iter_detail``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.adana import (
    _DETAIL_URL,
    _LISTING_URL,
    CITY_NAME,
    AdanaScraper,
    _normalize_number,
    _parse_detail_header_date,
    _parse_detail_tables,
    _parse_listing,
    _row_to_price,
    _split_name_and_variety,
    _to_decimal,
)

LISTING_HTML = """
<html><body>
<div class="card event-list-box">
  <span>11/05/2026</span>
  <a href="/tr/hal-detay/2611">Detay</a>
</div>
<div class="card event-list-box">
  <span>10/05/2026</span>
  <a href="/tr/hal-detay/2610">Detay</a>
</div>
</body></html>
"""

EMPTY_LISTING_HTML = "<html><body><p>No entries</p></body></html>"

DETAIL_HTML = """
<html><body>
<h4>11/05/2026 Tarihli Hal Fiyat Listesi</h4>
<table class="table table-striped"><tbody>
  <tr><td>BİBER(ÜÇ BURUN KÖY)</td><td>KG</td><td>10.00</td><td>15.00</td></tr>
</tbody></table>
<table class="table table-striped"><tbody>
  <tr><td>MUZ</td><td>KG</td><td>60.00</td><td>70.00</td></tr>
</tbody></table>
</body></html>
"""

EMPTY_DETAIL_HTML = """
<html><body>
<h4>11/05/2026 Tarihli Hal Fiyat Listesi</h4>
<table class="table table-striped"><tbody></tbody></table>
</body></html>
"""


class TestParseListing:
    def test_extracts_date_and_detail_id_pairs(self) -> None:
        entries = _parse_listing(LISTING_HTML)
        assert entries == [
            (date(2026, 5, 11), "2611"),
            (date(2026, 5, 10), "2610"),
        ]

    def test_returns_empty_when_no_cards(self) -> None:
        assert _parse_listing(EMPTY_LISTING_HTML) == []


class TestParseDetailHeaderDate:
    def test_parses_header_date(self) -> None:
        assert _parse_detail_header_date(DETAIL_HTML) == date(2026, 5, 11)

    def test_returns_none_when_missing(self) -> None:
        assert _parse_detail_header_date("<h4>no date</h4>") is None


class TestParseDetailTables:
    def test_extracts_rows_from_every_striped_table(self) -> None:
        rows = _parse_detail_tables(DETAIL_HTML)
        assert rows == [
            {"product": "BİBER(ÜÇ BURUN KÖY)", "unit": "KG", "low": "10.00", "high": "15.00"},
            {"product": "MUZ", "unit": "KG", "low": "60.00", "high": "70.00"},
        ]

    def test_returns_empty_for_empty_tbody(self) -> None:
        assert _parse_detail_tables(EMPTY_DETAIL_HTML) == []


class TestNormalizeNumber:
    def test_dot_decimal_separator_preserved(self) -> None:
        assert _normalize_number("10.00") == "10.00"


class TestToDecimal:
    def test_parses_dot_decimal(self) -> None:
        assert _to_decimal("10.00") == Decimal("10.00")

    def test_unparseable_returns_zero(self) -> None:
        assert _to_decimal("") == Decimal(0)


class TestSplitNameAndVariety:
    def test_splits_and_title_cases(self) -> None:
        assert _split_name_and_variety("DOMATES(SALKIM)") == ("Domates", "Salkim")

    def test_no_parenthetical_still_title_cases(self) -> None:
        assert _split_name_and_variety("MUZ") == ("Muz", None)

    def test_dotted_capital_i_title_casing_quirk(self) -> None:
        # `_titlecase_tr` uses plain str.capitalize(), which is not
        # locale-aware: Python lower-cases Turkish dotted "İ" to "i" plus a
        # combining dot-above (U+0307) rather than a plain ASCII "i". This
        # test pins that known, pre-existing behavior so a future change to
        # the (mis-named) "_tr" helper doesn't silently alter output.
        name, variety = _split_name_and_variety("BİBER(ÜÇ BURUN KÖY)")
        assert name == "Bi̇ber"
        assert variety == "Üç Burun Köy"


class TestRowToPrice:
    def test_maps_row_with_midpoint_and_title_case(self) -> None:
        row = {"product": "DOMATES(SALKIM)", "unit": "KG", "low": "10.00", "high": "15.00"}
        price = _row_to_price(row, date(2026, 5, 11))
        assert price.city_name == CITY_NAME
        assert price.product_name == "Domates"
        assert price.product_variety == "Salkim"
        assert price.product_category is None
        assert price.average_price == Decimal("12.5000")
        assert price.unit_name == "Kg"


@pytest.mark.asyncio
async def test_discover_entries_then_iter_detail_end_to_end(allow_robots: None) -> None:
    cutoff = date(2026, 5, 1)
    async with respx.mock(assert_all_called=False) as router:
        router.get(_LISTING_URL).mock(return_value=httpx.Response(200, text=LISTING_HTML))
        router.get(f"{_LISTING_URL}/5").mock(
            return_value=httpx.Response(200, text=EMPTY_LISTING_HTML)
        )
        router.get(_DETAIL_URL.format(detail_id="2611")).mock(
            return_value=httpx.Response(200, text=DETAIL_HTML)
        )
        router.get(_DETAIL_URL.format(detail_id="2610")).mock(
            return_value=httpx.Response(200, text=EMPTY_DETAIL_HTML)
        )
        scraper = AdanaScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            entries = await scraper._discover_entries(client, cutoff)
            assert entries == [(date(2026, 5, 11), "2611"), (date(2026, 5, 10), "2610")]

            prices_2611 = [p async for p in scraper._iter_detail(client, "2611", date(2026, 5, 11))]
            prices_2610 = [p async for p in scraper._iter_detail(client, "2610", date(2026, 5, 10))]

    assert len(prices_2611) == 2
    names = {p.product_name for p in prices_2611}
    # "Bi̇ber" (not "Biber") is the real, if surprising, output for
    # "BİBER" — see TestSplitNameAndVariety.test_dotted_capital_i_title_casing_quirk.
    assert names == {"Bi̇ber", "Muz"}
    assert prices_2610 == []


@pytest.mark.asyncio
async def test_discover_entries_returns_empty_for_empty_listing(allow_robots: None) -> None:
    async with respx.mock(assert_all_called=False) as router:
        router.get(_LISTING_URL).mock(return_value=httpx.Response(200, text=EMPTY_LISTING_HTML))
        scraper = AdanaScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            entries = await scraper._discover_entries(client, date(2026, 5, 1))

    assert entries == []


@pytest.mark.asyncio
async def test_iter_detail_uses_header_date_over_listing_date(allow_robots: None) -> None:
    # The listing said 10/05/2026, but the detail page's own <h4> says
    # 11/05/2026 — the detail header must win.
    async with respx.mock(assert_all_called=True) as router:
        router.get(_DETAIL_URL.format(detail_id="9999")).mock(
            return_value=httpx.Response(200, text=DETAIL_HTML)
        )
        scraper = AdanaScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_detail(client, "9999", date(2026, 5, 10))]

    assert all(p.bulletin_date == date(2026, 5, 11) for p in prices)
