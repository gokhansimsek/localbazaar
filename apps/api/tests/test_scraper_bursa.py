"""Unit tests for the Bursa Metropolitan Municipality hal-prices scraper.

Covers bulletin-heading date extraction, per-tab table parsing (category from
the nav-link label), midpoint math on a ``"low - high"`` range, unit
normalization across the source's many "kg" spellings, and an end-to-end
respx-mocked ``BursaScraper.iter_prices`` run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from local_bazaar.scrapers.cities.bursa import (
    CITY_NAME,
    URL,
    BursaScraper,
    _bulletin_date_from_heading,
    _midpoint,
    _normalize_unit,
    _parse_tabs,
    _row_to_price,
)

BULLETIN_HTML = """
<html><body>
<h3>11.05.2026 Tarihli Hal Fiyatları</h3>
<ul class="nav">
  <li><a class="nav-link" href="#tab-2">Meyve</a></li>
  <li><a class="nav-link" href="#tab-3">Sebze</a></li>
  <li><a class="nav-link" href="#tab-9">Pelajik</a></li>
</ul>
<div class="tab-pane" id="tab-2">
  <table id="datatable"><tbody>
    <tr><td>Armut</td><td>Kg.</td><td>8,00 - 80,00</td></tr>
  </tbody></table>
</div>
<div class="tab-pane" id="tab-3">
  <table id="datatable"><tbody>
    <tr><td>Domates</td><td>(kg)</td><td>25,00</td></tr>
  </tbody></table>
</div>
<div class="tab-pane" id="tab-9">
  <table id="datatable"><tbody>
    <tr><td>Palamut</td><td>Kg</td><td>90,00</td></tr>
  </tbody></table>
</div>
</body></html>
"""

EMPTY_BULLETIN_HTML = """
<html><body>
<h3>11.05.2026 Tarihli Hal Fiyatları</h3>
<div class="tab-pane" id="tab-2"><table id="datatable"><tbody></tbody></table></div>
</body></html>
"""


class TestBulletinDateFromHeading:
    def test_parses_heading_date(self) -> None:
        assert _bulletin_date_from_heading(BULLETIN_HTML) == date(2026, 5, 11)

    def test_returns_none_when_missing(self) -> None:
        assert _bulletin_date_from_heading("<h3>no date here</h3>") is None


class TestParseTabs:
    def test_extracts_rows_from_allowed_categories_only(self) -> None:
        rows = _parse_tabs(BULLETIN_HTML)
        # Pelajik (seafood) tab is filtered out even though it has a table.
        assert [r["product_name"] for r in rows] == ["Armut", "Domates"]
        assert rows[0]["category"] == "Meyve"
        assert rows[1]["category"] == "Sebze"

    def test_returns_empty_for_empty_tbody(self) -> None:
        assert _parse_tabs(EMPTY_BULLETIN_HTML) == []


class TestNormalizeUnit:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Kg.", "Kg"),
            ("(kg)", "Kg"),
            ("kğ", "Kg"),
            ("Adet", "Adet"),
            ("", "Kg"),
        ],
    )
    def test_normalizes_kilogram_spellings(self, raw: str, expected: str) -> None:
        assert _normalize_unit(raw) == expected


class TestMidpoint:
    def test_range_midpoint(self) -> None:
        assert _midpoint("8,00 - 80,00") == Decimal("44.0000")

    def test_single_value_range(self) -> None:
        assert _midpoint("25,00") == Decimal("25.0000")

    def test_unparseable_returns_none(self) -> None:
        assert _midpoint("n/a") is None


class TestRowToPrice:
    def test_maps_row_to_product_price(self) -> None:
        row = {
            "product_name": "Armut",
            "unit": "Kg.",
            "price_range": "8,00 - 80,00",
            "category": "Meyve",
        }
        price = _row_to_price(row, date(2026, 5, 11))
        assert price is not None
        assert price.city_name == CITY_NAME
        assert price.product_variety is None
        assert price.product_category == "Meyve"
        assert price.average_price == Decimal("44.0000")
        assert price.unit_name == "Kg"

    def test_unparseable_price_returns_none(self) -> None:
        row = {"product_name": "X", "unit": "Kg", "price_range": "n/a", "category": "Sebze"}
        assert _row_to_price(row, date(2026, 5, 11)) is None


@pytest.mark.asyncio
async def test_iter_prices_yields_records_for_allowed_categories(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(URL, params={"tarih": "2026-05-11"}).mock(
            return_value=httpx.Response(200, text=BULLETIN_HTML)
        )
        scraper = BursaScraper()
        prices = [p async for p in scraper.iter_prices(target)]

    assert len(prices) == 2
    names = {p.product_name for p in prices}
    assert names == {"Armut", "Domates"}
    armut = next(p for p in prices if p.product_name == "Armut")
    assert armut.average_price == Decimal("44.0000")
    assert armut.unit_name == "Kg"
    assert armut.bulletin_date == target


@pytest.mark.asyncio
async def test_iter_prices_yields_nothing_for_empty_bulletin(allow_robots: None) -> None:
    target = date(2026, 5, 11)
    async with respx.mock(assert_all_called=True) as router:
        router.get(URL, params={"tarih": "2026-05-11"}).mock(
            return_value=httpx.Response(200, text=EMPTY_BULLETIN_HTML)
        )
        scraper = BursaScraper()
        prices = [p async for p in scraper.iter_prices(target)]

    assert prices == []
