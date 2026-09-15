"""Unit tests for the Ankara (ankara.bel.tr) hal-prices scraper.

Covers CSRF-token extraction, table parsing, the ``Tarih``-cell-is-authoritative
date rule, midpoint math, name/variety splitting, and an end-to-end respx-mocked
``AnkaraScraper.iter_prices`` run across the three POSTed product types.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.ankara import (
    ANKARA_CITY_NAME,
    URL,
    AnkaraScraper,
    _extract_csrf_token,
    _midpoint,
    _parse_dmy,
    _parse_table,
    _split_variety,
    _to_decimal,
)

LANDING_HTML = """
<html><head><meta name="csrf-token" content="TOKEN123" /></head><body></body></html>
"""

TABLE_HTML = """
<table class="table table-custom">
  <thead><tr><th>Ürün Adı</th><th>Ürün Türü</th><th>Birim</th>
  <th>En Düşük Fiyat (₺)</th><th>En Yüksek Fiyat (₺)</th><th>Tarih</th></tr></thead>
  <tbody>
    <tr><td>Armut (Deveci)</td><td>Meyve</td><td>Kg</td>
        <td>32,40</td><td>40,00</td><td>11.05.2026</td></tr>
    <tr><td>Elma</td><td>Meyve</td><td>Kg</td>
        <td>18,00</td><td>22,00</td><td>11.05.2026</td></tr>
  </tbody>
</table>
"""

EMPTY_TABLE_HTML = """
<table class="table table-custom">
  <thead><tr><th>Ürün Adı</th><th>Ürün Türü</th><th>Birim</th>
  <th>En Düşük Fiyat (₺)</th><th>En Yüksek Fiyat (₺)</th><th>Tarih</th></tr></thead>
  <tbody></tbody>
</table>
"""


class TestExtractCsrfToken:
    def test_reads_token_from_meta_tag(self) -> None:
        assert _extract_csrf_token(LANDING_HTML) == "TOKEN123"

    def test_returns_none_when_missing(self) -> None:
        assert _extract_csrf_token("<html></html>") is None


class TestParseTable:
    def test_extracts_data_rows(self) -> None:
        rows = _parse_table(TABLE_HTML)
        assert len(rows) == 2
        assert rows[0] == {
            "product_name": "Armut (Deveci)",
            "product_type": "Meyve",
            "unit_name": "Kg",
            "min_price": "32,40",
            "max_price": "40,00",
            "bulletin_date": "11.05.2026",
        }

    def test_returns_empty_for_empty_tbody(self) -> None:
        assert _parse_table(EMPTY_TABLE_HTML) == []

    def test_returns_empty_when_table_missing(self) -> None:
        assert _parse_table("<html>no table</html>") == []


class TestSplitVariety:
    def test_splits_trailing_parenthetical(self) -> None:
        assert _split_variety("Armut (Deveci)") == ("Armut", "Deveci")

    def test_no_parenthetical_returns_none_variety(self) -> None:
        assert _split_variety("Elma") == ("Elma", None)


class TestParseDmy:
    def test_parses_valid_date(self) -> None:
        assert _parse_dmy("11.05.2026") == date(2026, 5, 11)

    def test_returns_none_for_empty(self) -> None:
        assert _parse_dmy("") is None

    def test_returns_none_for_malformed(self) -> None:
        assert _parse_dmy("not-a-date") is None


class TestMidpoint:
    def test_averages_both_bounds(self) -> None:
        assert _midpoint(Decimal("32.40"), Decimal("40.00")) == Decimal("36.20")

    def test_both_zero_returns_none(self) -> None:
        assert _midpoint(Decimal(0), Decimal(0)) is None

    def test_falls_back_to_single_bound(self) -> None:
        assert _midpoint(Decimal(0), Decimal("40.00")) == Decimal("40.00")
        assert _midpoint(Decimal("32.40"), Decimal(0)) == Decimal("32.40")


class TestToDecimal:
    def test_parses_turkish_thousands_and_decimal(self) -> None:
        assert _to_decimal("1.234,56") == Decimal("1234.56")

    def test_unparseable_returns_zero(self) -> None:
        assert _to_decimal("n/a") == Decimal(0)


@pytest.mark.asyncio
async def test_iter_prices_yields_records_across_product_types(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(URL).mock(return_value=httpx.Response(200, text=LANDING_HTML))
        router.post(URL, data__contains={"type": "fruit"}).mock(
            return_value=httpx.Response(200, text=TABLE_HTML)
        )
        router.post(URL, data__contains={"type": "vegetable"}).mock(
            return_value=httpx.Response(200, text=EMPTY_TABLE_HTML)
        )
        router.post(URL, data__contains={"type": "imported"}).mock(
            return_value=httpx.Response(200, text=EMPTY_TABLE_HTML)
        )

        scraper = AnkaraScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            token = await scraper._bootstrap(client)
            assert token == "TOKEN123"
            prices = [p async for p in scraper.iter_prices(client, token, target)]

    assert len(prices) == 2
    armut = next(p for p in prices if p.product_name == "Armut")
    assert armut.city_name == ANKARA_CITY_NAME
    assert armut.product_variety == "Deveci"
    assert armut.average_price == Decimal("36.20")
    assert armut.bulletin_date == date(2026, 5, 11)
    assert armut.product_category == "Meyve"


@pytest.mark.asyncio
async def test_iter_prices_yields_nothing_when_all_types_empty(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(URL).mock(return_value=httpx.Response(200, text=LANDING_HTML))
        router.post(URL).mock(return_value=httpx.Response(200, text=EMPTY_TABLE_HTML))

        scraper = AnkaraScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            token = await scraper._bootstrap(client)
            assert token is not None
            prices = [p async for p in scraper.iter_prices(client, token, target)]

    assert prices == []
