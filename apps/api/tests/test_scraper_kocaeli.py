"""Unit tests for the Kocaeli Büyükşehir Belediyesi hal-prices scraper.

Covers the single-table parsing (category filter drops non-produce rows),
name/variety splitting, midpoint math, unit normalization, and an end-to-end
respx-mocked ``KocaeliScraper._iter_day`` run against the date-in-path URL.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.kocaeli import (
    _URL_TEMPLATE,
    CITY_NAME,
    KocaeliScraper,
    _normalize_unit,
    _parse_table,
    _row_to_price,
    _split_name_and_variety,
    _to_decimal,
)

TABLE_HTML = """
<table>
  <tr><td>Ürün Adı</td><td>Kategori</td><td>Birim</td><td>En az</td><td>En çok</td></tr>
  <tr><td>Armut (Deveci)</td><td>Meyve</td><td>Kg</td><td>90</td><td>90</td></tr>
  <tr><td>Asma Yaprağı</td><td>Sebze</td><td>Kg</td><td>70</td><td>125</td></tr>
  <tr><td>Ananas</td><td>Meyve</td><td>Ad</td><td>150</td><td>165</td></tr>
  <tr><td>Palamut</td><td>Su Ürünleri</td><td>Kg</td><td>200</td><td>250</td></tr>
</table>
"""

EMPTY_TABLE_HTML = """
<table>
  <tr><td>Ürün Adı</td><td>Kategori</td><td>Birim</td><td>En az</td><td>En çok</td></tr>
</table>
"""


class TestParseTable:
    def test_extracts_produce_rows_and_skips_fish_category(self) -> None:
        rows = _parse_table(TABLE_HTML)
        assert [r["product"] for r in rows] == ["Armut (Deveci)", "Asma Yaprağı", "Ananas"]

    def test_returns_empty_when_no_data_rows(self) -> None:
        assert _parse_table(EMPTY_TABLE_HTML) == []

    def test_returns_empty_when_table_missing(self) -> None:
        assert _parse_table("<html>no table</html>") == []


class TestSplitNameAndVariety:
    def test_splits_parenthetical(self) -> None:
        assert _split_name_and_variety("Armut (Deveci)") == ("Armut", "Deveci")

    def test_no_parenthetical(self) -> None:
        assert _split_name_and_variety("Ananas") == ("Ananas", None)


class TestNormalizeUnit:
    @pytest.mark.parametrize(
        "raw,expected", [("Kg", "Kg"), ("Ad", "Adet"), ("Adet", "Adet"), ("kğ", "Kg")]
    )
    def test_maps_known_units(self, raw: str, expected: str) -> None:
        assert _normalize_unit(raw) == expected


class TestToDecimal:
    def test_parses_plain_integer(self) -> None:
        assert _to_decimal("90") == Decimal("90")

    def test_parses_turkish_decimal(self) -> None:
        assert _to_decimal("1.234,56") == Decimal("1234.56")

    def test_unparseable_returns_zero(self) -> None:
        assert _to_decimal("n/a") == Decimal(0)


class TestRowToPrice:
    def test_maps_row_with_midpoint(self) -> None:
        row = {
            "product": "Asma Yaprağı",
            "category": "Sebze",
            "unit": "Kg",
            "low": "70",
            "high": "125",
        }
        price = _row_to_price(row, date(2026, 5, 11))
        assert price.city_name == CITY_NAME
        assert price.product_variety is None
        assert price.product_category == "Sebze"
        assert price.average_price == Decimal("97.5000")
        assert price.unit_name == "Kg"

    def test_equal_bounds_yield_that_value(self) -> None:
        row = {
            "product": "Armut (Deveci)",
            "category": "Meyve",
            "unit": "Kg",
            "low": "90",
            "high": "90",
        }
        price = _row_to_price(row, date(2026, 5, 11))
        assert price.average_price == Decimal("90.0000")
        assert price.product_variety == "Deveci"


@pytest.mark.asyncio
async def test_iter_day_yields_produce_rows_only(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    url = _URL_TEMPLATE.format(date="2026-05-11")
    async with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, text=TABLE_HTML))
        scraper = KocaeliScraper()
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_day(client, target)]

    assert len(prices) == 3
    names = {p.product_name for p in prices}
    assert names == {"Armut", "Asma Yaprağı", "Ananas"}
    assert all(p.bulletin_date == target for p in prices)


@pytest.mark.asyncio
async def test_iter_day_yields_nothing_for_empty_bulletin(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    url = _URL_TEMPLATE.format(date="2026-05-11")
    async with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, text=EMPTY_TABLE_HTML))
        scraper = KocaeliScraper()
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_day(client, target)]

    assert prices == []
