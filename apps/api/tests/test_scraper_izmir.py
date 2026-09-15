"""Unit tests for the İzmir Büyükşehir Belediyesi hal-prices scraper.

İzmir is the one per-city source that publishes a real ``Ortalama`` (average)
column directly, rather than a min/max range we'd have to midpoint ourselves —
these tests specifically assert the average is used as-is. Also covers
Turkish title-casing of the ALL-CAPS source cells and an end-to-end
respx-mocked ``IzmirScraper._iter_day`` run across the three ``tip`` requests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.izmir import (
    _URL,
    CITY_NAME,
    IzmirScraper,
    _normalize_unit,
    _parse_table,
    _row_to_price,
    _titlecase_tr,
    _to_decimal,
)

TABLE_HTML_SEBZE = """
<table class="table table-condensed">
  <thead><tr><th>Tip</th><th>Adı</th><th>Birimi</th><th>En Az</th><th>En Çok</th><th>Ortalama</th></tr></thead>
  <tbody>
    <tr><td>SEBZE</td><td>BARBUNYA TAZE</td><td>KG</td><td>28,00</td><td>35,00</td><td>31,50</td></tr>
  </tbody>
</table>
"""

TABLE_HTML_MEYVE = """
<table class="table table-condensed">
  <thead><tr><th>Tip</th><th>Adı</th><th>Birimi</th><th>En Az</th><th>En Çok</th><th>Ortalama</th></tr></thead>
  <tbody>
    <tr><td>MEYVE</td><td>MUZ</td><td>KG</td><td>60,00</td><td>70,00</td><td>65,50</td></tr>
  </tbody>
</table>
"""

EMPTY_TABLE_HTML = """
<table class="table table-condensed">
  <thead><tr><th>Tip</th><th>Adı</th><th>Birimi</th><th>En Az</th><th>En Çok</th><th>Ortalama</th></tr></thead>
  <tbody></tbody>
</table>
"""


class TestParseTable:
    def test_extracts_rows_with_average_column(self) -> None:
        rows = _parse_table(TABLE_HTML_SEBZE)
        assert rows == [
            {
                "category": "SEBZE",
                "product": "BARBUNYA TAZE",
                "unit": "KG",
                "low": "28,00",
                "high": "35,00",
                "average": "31,50",
            }
        ]

    def test_returns_empty_for_empty_tbody(self) -> None:
        assert _parse_table(EMPTY_TABLE_HTML) == []

    def test_returns_empty_when_table_missing(self) -> None:
        assert _parse_table("<html>no table</html>") == []


class TestTitlecaseTr:
    def test_title_cases_multi_word_string(self) -> None:
        assert _titlecase_tr("BARBUNYA TAZE") == "Barbunya Taze"

    def test_single_word(self) -> None:
        assert _titlecase_tr("MUZ") == "Muz"


class TestNormalizeUnit:
    @pytest.mark.parametrize("raw,expected", [("KG", "Kg"), ("ADET", "Adet"), ("", "Kg")])
    def test_maps_known_units(self, raw: str, expected: str) -> None:
        assert _normalize_unit(raw) == expected


class TestToDecimal:
    def test_parses_turkish_decimal(self) -> None:
        assert _to_decimal("31,50") == Decimal("31.50")

    def test_unparseable_returns_zero(self) -> None:
        assert _to_decimal("") == Decimal(0)


class TestRowToPrice:
    def test_uses_published_average_directly_not_a_midpoint(self) -> None:
        row = {
            "category": "SEBZE",
            "product": "BARBUNYA TAZE",
            "unit": "KG",
            "low": "28,00",
            "high": "35,00",
            "average": "31,50",
        }
        price = _row_to_price(row, date(2026, 5, 11))
        # The naive midpoint of (28.00, 35.00) would be 31.50 too, so pick a case
        # where midpoint and published average differ to prove we use Ortalama.
        assert price.average_price == Decimal("31.50")
        assert price.city_name == CITY_NAME
        assert price.product_name == "Barbunya Taze"
        assert price.product_category == "Sebze"
        assert price.product_variety is None
        assert price.unit_name == "Kg"

    def test_average_differs_from_naive_midpoint_and_average_wins(self) -> None:
        # Midpoint of (60, 70) is 65.00, but the source publishes 65.50 — the
        # scraper must use the published value, not compute its own midpoint.
        row = {
            "category": "MEYVE",
            "product": "MUZ",
            "unit": "KG",
            "low": "60,00",
            "high": "70,00",
            "average": "65,50",
        }
        price = _row_to_price(row, date(2026, 5, 11))
        assert price.average_price == Decimal("65.50")


@pytest.mark.asyncio
async def test_iter_day_yields_records_across_tips(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(_URL, params={"date": "2026-05-11", "tip": "1"}).mock(
            return_value=httpx.Response(200, text=TABLE_HTML_SEBZE)
        )
        router.get(_URL, params={"date": "2026-05-11", "tip": "2"}).mock(
            return_value=httpx.Response(200, text=TABLE_HTML_MEYVE)
        )
        router.get(_URL, params={"date": "2026-05-11", "tip": "3"}).mock(
            return_value=httpx.Response(200, text=EMPTY_TABLE_HTML)
        )
        scraper = IzmirScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_day(client, target)]

    assert len(prices) == 2
    barbunya = next(p for p in prices if p.product_name == "Barbunya Taze")
    assert barbunya.average_price == Decimal("31.50")
    muz = next(p for p in prices if p.product_name == "Muz")
    assert muz.average_price == Decimal("65.50")


@pytest.mark.asyncio
async def test_iter_day_yields_nothing_when_all_tips_empty(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        for tip in ("1", "2", "3"):
            router.get(_URL, params={"date": "2026-05-11", "tip": tip}).mock(
                return_value=httpx.Response(200, text=EMPTY_TABLE_HTML)
            )
        scraper = IzmirScraper(request_sleep=0)
        async with httpx.AsyncClient() as client:
            prices = [p async for p in scraper._iter_day(client, target)]

    assert prices == []
