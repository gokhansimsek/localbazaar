"""Unit tests for the Konya Metropolitan Municipality hal-prices scraper.

Covers the ``<select>``-driven available-dates discovery, the two-table
(Sebze/Meyve) bulletin parsing with its in-``tbody`` label row, name/variety
splitting, midpoint math, and an end-to-end respx-mocked
``KonyaScraper.iter_prices`` run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.konya import (
    CITY_NAME,
    URL,
    KonyaScraper,
    _extract_available_dates,
    _midpoint_decimal,
    _split_name_variety,
)

LANDING_HTML = """
<html><body>
<select id="tarih" name="tarih">
  <option value="2026-05-09">09.05.2026</option>
  <option value="2026-05-10">10.05.2026</option>
  <option value="2026-05-11" selected>11.05.2026</option>
</select>
<table>
  <thead><tr><th>SEBZE FİYATLARI</th></tr></thead>
  <tbody>
    <tr><td><strong>Ürün</strong></td><td>Birim</td><td>En Düşük</td><td>En Yüksek</td></tr>
    <tr><td>DOMATES (SALKIM)</td><td>Kg</td><td>15,00</td><td>20,00</td></tr>
  </tbody>
</table>
<table>
  <thead><tr><th>MEYVE FİYATLARI</th></tr></thead>
  <tbody>
    <tr><td><strong>Ürün</strong></td><td>Birim</td><td>En Düşük</td><td>En Yüksek</td></tr>
    <tr><td>ELMA (GRANNY SMİTH)</td><td>Kg</td><td>18,00</td><td>22,00</td></tr>
  </tbody>
</table>
</body></html>
"""

EMPTY_BULLETIN_HTML = """
<html><body>
<table><thead><tr><th>SEBZE FİYATLARI</th></tr></thead><tbody></tbody></table>
</body></html>
"""


class TestExtractAvailableDates:
    def test_reads_every_option_value(self) -> None:
        dates = _extract_available_dates(LANDING_HTML)
        assert dates == [date(2026, 5, 9), date(2026, 5, 10), date(2026, 5, 11)]

    def test_returns_empty_when_select_missing(self) -> None:
        assert _extract_available_dates("<html>no select</html>") == []


class TestSplitNameVariety:
    def test_splits_parenthetical_variety(self) -> None:
        assert _split_name_variety("ELMA (GRANNY SMİTH)") == ("ELMA", "GRANNY SMİTH")

    def test_no_parenthetical_returns_none(self) -> None:
        assert _split_name_variety("DOMATES") == ("DOMATES", None)


class TestMidpointDecimal:
    def test_averages_both_bounds(self) -> None:
        assert _midpoint_decimal("15,00", "20,00") == Decimal("17.5000")

    def test_falls_back_to_single_bound(self) -> None:
        assert _midpoint_decimal("", "20,00") == Decimal("20.00")
        assert _midpoint_decimal("15,00", "") == Decimal("15.00")

    def test_both_missing_returns_none(self) -> None:
        assert _midpoint_decimal("", "") is None


class TestParseBulletin:
    def test_parses_both_category_tables(self) -> None:
        prices = KonyaScraper._parse_bulletin(LANDING_HTML, date(2026, 5, 11))
        assert len(prices) == 2
        domates = next(p for p in prices if p.product_name == "DOMATES")
        assert domates.city_name == CITY_NAME
        assert domates.product_variety == "SALKIM"
        assert domates.product_category == "Sebze"
        assert domates.average_price == Decimal("17.5000")
        elma = next(p for p in prices if p.product_name == "ELMA")
        assert elma.product_variety == "GRANNY SMİTH"
        assert elma.product_category == "Meyve"

    def test_empty_tbody_yields_no_prices(self) -> None:
        assert KonyaScraper._parse_bulletin(EMPTY_BULLETIN_HTML, date(2026, 5, 11)) == []


@pytest.mark.asyncio
async def test_iter_prices_for_explicit_date(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(URL, params={"tarih": "2026-05-11"}).mock(
            return_value=httpx.Response(200, text=LANDING_HTML)
        )
        scraper = KonyaScraper()
        prices = [p async for p in scraper.iter_prices(target)]

    assert len(prices) == 2
    assert all(p.bulletin_date == target for p in prices)


@pytest.mark.asyncio
async def test_iter_prices_yields_nothing_for_empty_bulletin(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(URL, params={"tarih": "2026-05-11"}).mock(
            return_value=httpx.Response(200, text=EMPTY_BULLETIN_HTML)
        )
        scraper = KonyaScraper()
        prices = [p async for p in scraper.iter_prices(target)]

    assert prices == []
