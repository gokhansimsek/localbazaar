"""Unit tests for the Istanbul (IBB) hal-prices scraper.

Covers the AJAX-fragment parsing (``_parse_table``), the raw-row → ProductPrice
mapping (``_row_to_price``, midpoint math, Turkish decimal parsing, name/variety
splitting, unit normalization), and an end-to-end respx-mocked
``IstanbulHalScraper.iter_prices`` run across the three category requests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.istanbul import (
    AJAX_URL,
    CITY_NAME,
    IstanbulHalScraper,
    _normalize_unit,
    _parse_table,
    _row_to_price,
    _split_name_and_variety,
    _to_decimal,
)

SAMPLE_FRAGMENT_HTML = """
<table class="tableClass">
  <tr><th>Urun Adı</th><th>Birim</th><th>En Düşük Fiyat</th><th>En Yüksek Fiyat</th></tr>
  <tr><td>Armut (Akça)</td><td>Kilogram</td>
      <td>155,00<span> TL</span></td>
      <td>170,00<span> TL</span></td></tr>
  <tr><td>Muz</td><td>Kilogram</td>
      <td>60,00 TL</td>
      <td>65,00 TL</td></tr>
</table>
"""

EMPTY_FRAGMENT_HTML = """
<table class="tableClass">
  <tr><th>Urun Adı</th><th>Birim</th><th>En Düşük Fiyat</th><th>En Yüksek Fiyat</th></tr>
</table>
"""


class TestParseTable:
    def test_extracts_data_rows_only(self) -> None:
        rows = _parse_table(SAMPLE_FRAGMENT_HTML)
        assert len(rows) == 2
        assert rows[0] == {
            "product_name_raw": "Armut (Akça)",
            "unit_name": "Kilogram",
            "min_price": "155,00TL",
            "max_price": "170,00TL",
        }

    def test_returns_empty_for_header_only_fragment(self) -> None:
        assert _parse_table(EMPTY_FRAGMENT_HTML) == []

    def test_returns_empty_when_no_table_present(self) -> None:
        assert _parse_table("<div>no data</div>") == []


class TestSplitNameAndVariety:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Armut", ("Armut", None)),
            ("Armut (Akça)", ("Armut", "Akça")),
            ("Karpuz (1.Kalite)", ("Karpuz", "1.Kalite")),
        ],
    )
    def test_splits_parenthetical_variety(self, raw: str, expected: tuple[str, str | None]) -> None:
        assert _split_name_and_variety(raw) == expected


class TestNormalizeUnit:
    def test_maps_kilogram_to_kg(self) -> None:
        assert _normalize_unit("Kilogram") == "Kg"

    def test_maps_adet_to_adet(self) -> None:
        assert _normalize_unit("Adet") == "Adet"

    def test_unknown_unit_is_title_cased(self) -> None:
        assert _normalize_unit("demet") == "Demet"


class TestToDecimal:
    def test_parses_turkish_decimal_comma(self) -> None:
        assert _to_decimal("155,00 TL") == Decimal("155.00")

    def test_returns_zero_for_empty_string(self) -> None:
        assert _to_decimal("") == Decimal(0)

    def test_returns_zero_for_unparseable_text(self) -> None:
        assert _to_decimal("—") == Decimal(0)


class TestRowToPrice:
    def test_computes_midpoint_and_maps_fields(self) -> None:
        row = {
            "product_name_raw": "Armut (Akça)",
            "unit_name": "Kilogram",
            "min_price": "155,00 TL",
            "max_price": "170,00 TL",
        }
        price = _row_to_price(row, date(2026, 5, 11))
        assert price is not None
        assert price.city_name == CITY_NAME
        assert price.bulletin_date == date(2026, 5, 11)
        assert price.product_name == "Armut"
        assert price.product_variety == "Akça"
        assert price.product_category is None
        assert price.average_price == Decimal("162.5000")
        assert price.unit_name == "Kg"
        assert price.transaction_volume is None

    def test_both_prices_zero_returns_none(self) -> None:
        row = {
            "product_name_raw": "Muz",
            "unit_name": "Kg",
            "min_price": "",
            "max_price": "",
        }
        assert _row_to_price(row, date(2026, 5, 11)) is None

    def test_blank_product_name_returns_none(self) -> None:
        row = {
            "product_name_raw": "",
            "unit_name": "Kg",
            "min_price": "10,00",
            "max_price": "20,00",
        }
        assert _row_to_price(row, date(2026, 5, 11)) is None


@pytest.mark.asyncio
async def test_iter_prices_yields_records_across_all_categories(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(AJAX_URL, params={"kategori": "5"}).mock(
            return_value=httpx.Response(200, text=SAMPLE_FRAGMENT_HTML)
        )
        router.get(AJAX_URL, params={"kategori": "6"}).mock(
            return_value=httpx.Response(200, text=EMPTY_FRAGMENT_HTML)
        )
        router.get(AJAX_URL, params={"kategori": "7"}).mock(
            return_value=httpx.Response(200, text=EMPTY_FRAGMENT_HTML)
        )
        scraper = IstanbulHalScraper(request_sleep=0)
        prices = [p async for p in scraper.iter_prices(target)]

    assert len(prices) == 2
    names = {p.product_name for p in prices}
    assert names == {"Armut", "Muz"}
    armut = next(p for p in prices if p.product_name == "Armut")
    assert armut.average_price == Decimal("162.5000")
    assert armut.bulletin_date == target


@pytest.mark.asyncio
async def test_iter_prices_yields_nothing_when_all_categories_empty(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        for kategori in ("5", "6", "7"):
            router.get(AJAX_URL, params={"kategori": kategori}).mock(
                return_value=httpx.Response(200, text=EMPTY_FRAGMENT_HTML)
            )
        scraper = IstanbulHalScraper(request_sleep=0)
        prices = [p async for p in scraper.iter_prices(target)]

    assert prices == []
