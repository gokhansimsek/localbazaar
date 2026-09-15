"""Unit tests for the Şanlıurfa Büyükşehir Belediyesi hal-prices scraper.

Şanlıurfa is the one per-city source that uses a DOT decimal separator
(``"90.00"``) instead of the Turkish comma every other source uses — these
tests specifically assert numbers are NOT mangled by a comma/dot swap. Also
covers the row-level ``Tarih`` cell overriding the requested date, and an
end-to-end respx-mocked ``SanliurfaScraper._iter_day`` run across both
product types.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.sanliurfa import (
    _URL,
    CITY_NAME,
    SanliurfaScraper,
    _normalize_number,
    _parse_table,
    _parse_tr_date,
    _row_to_price,
    _split_name_and_variety,
    _to_decimal,
)

TABLE_HTML_SEBZE = """
<table class="custom-table">
  <thead><tr><th>Ürün Adı</th><th>Ürün Türü</th><th>Birim</th>
  <th>En Düşük Fiyat (₺)</th><th>En Yüksek Fiyat (₺)</th><th>Tarih</th></tr></thead>
  <tbody>
    <tr><td>Biber Kapya (Sera)</td><td>Sebze</td><td>kg</td>
        <td>10.50</td><td>15.25</td><td>11.05.2026</td></tr>
  </tbody>
</table>
"""

EMPTY_TABLE_HTML = """
<table class="custom-table">
  <thead><tr><th>Ürün Adı</th><th>Ürün Türü</th><th>Birim</th>
  <th>En Düşük Fiyat (₺)</th><th>En Yüksek Fiyat (₺)</th><th>Tarih</th></tr></thead>
  <tbody></tbody>
</table>
"""


class TestParseTable:
    def test_extracts_data_rows(self) -> None:
        rows = _parse_table(TABLE_HTML_SEBZE)
        assert rows == [
            {
                "product": "Biber Kapya (Sera)",
                "category": "Sebze",
                "unit": "kg",
                "low": "10.50",
                "high": "15.25",
                "date": "11.05.2026",
            }
        ]

    def test_returns_empty_for_empty_tbody(self) -> None:
        assert _parse_table(EMPTY_TABLE_HTML) == []

    def test_returns_empty_when_table_missing(self) -> None:
        assert _parse_table("<html>no table</html>") == []


class TestNormalizeNumber:
    def test_dot_decimal_separator_is_preserved_not_swapped(self) -> None:
        # Unlike every other per-city source, Şanlıurfa uses a dot for the
        # decimal separator. A naive Turkish-style normalizer would turn
        # "1234.56" into "123456" by stripping the dot as a thousands
        # separator — this must NOT happen here.
        assert _normalize_number("1234.56") == "1234.56"

    def test_strips_currency_and_whitespace(self) -> None:
        assert _normalize_number("90.00 \xa0₺") == "90.00"


class TestToDecimal:
    def test_parses_dot_decimal(self) -> None:
        assert _to_decimal("10.50") == Decimal("10.50")

    def test_unparseable_returns_zero(self) -> None:
        assert _to_decimal("") == Decimal(0)


class TestSplitNameAndVariety:
    def test_splits_parenthetical(self) -> None:
        assert _split_name_and_variety("Biber Kapya (Sera)") == ("Biber Kapya", "Sera")

    def test_no_parenthetical(self) -> None:
        assert _split_name_and_variety("Domates") == ("Domates", None)


class TestParseTrDate:
    def test_parses_valid_date(self) -> None:
        assert _parse_tr_date("11.05.2026") == date(2026, 5, 11)

    def test_empty_returns_none(self) -> None:
        assert _parse_tr_date("") is None

    def test_malformed_returns_none(self) -> None:
        assert _parse_tr_date("not-a-date") is None


class TestRowToPrice:
    def test_uses_dot_decimal_prices_and_row_date(self) -> None:
        row = {
            "product": "Biber Kapya (Sera)",
            "category": "Sebze",
            "unit": "kg",
            "low": "10.50",
            "high": "15.25",
            "date": "11.05.2026",
        }
        price = _row_to_price(row, date(2026, 5, 1))
        assert price.city_name == CITY_NAME
        assert price.product_name == "Biber Kapya"
        assert price.product_variety == "Sera"
        assert price.average_price == Decimal("12.8750")
        assert price.unit_name == "Kg"
        # The row's own Tarih cell overrides the requested date.
        assert price.bulletin_date == date(2026, 5, 11)

    def test_falls_back_to_requested_date_when_row_date_missing(self) -> None:
        row = {
            "product": "Domates",
            "category": "Sebze",
            "unit": "kg",
            "low": "5.00",
            "high": "7.00",
            "date": "",
        }
        price = _row_to_price(row, date(2026, 5, 1))
        assert price.bulletin_date == date(2026, 5, 1)


@pytest.mark.asyncio
async def test_iter_day_yields_records_across_product_types(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(_URL, params={"product_type_id": "1"}).mock(
            return_value=httpx.Response(200, text=TABLE_HTML_SEBZE)
        )
        router.get(_URL, params={"product_type_id": "2"}).mock(
            return_value=httpx.Response(200, text=EMPTY_TABLE_HTML)
        )
        scraper = SanliurfaScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_day(client, target)]

    assert len(prices) == 1
    price = prices[0]
    assert price.product_name == "Biber Kapya"
    assert price.average_price == Decimal("12.8750")


@pytest.mark.asyncio
async def test_iter_day_yields_nothing_when_both_types_empty(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        for ptype in ("1", "2"):
            router.get(_URL, params={"product_type_id": ptype}).mock(
                return_value=httpx.Response(200, text=EMPTY_TABLE_HTML)
            )
        scraper = SanliurfaScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_day(client, target)]

    assert prices == []
