"""Unit tests for HTML parsing and form-state extraction in the hal.gov.tr scraper."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from local_bazaar.scrapers.hal_gov_tr import (
    NATIONAL_CITY_NAME,
    HalGovTrScraper,
    _discover_total_pages,
    _extract_grid_id,
    _extract_hidden_fields,
    _extract_html,
    _parse_table,
)

SAMPLE_TABLE_HTML = """
<html><body>
<form>
<input type="hidden" name="__VIEWSTATE" value="VIEWSTATE_TOKEN" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="GEN_TOKEN" />
<input type="hidden" name="__EVENTVALIDATION" value="VALIDATION_TOKEN" />
<input type="hidden" name="other_field" value="ignore_me" />
<div>Bülten Tarihi: 11.05.2026</div>
<table id="ctl00_ctl37_g_abc_123_gvFiyatlar">
  <tr><th>Ürün Adı</th><th>Cinsi</th><th>Türü</th><th>Fiyat</th><th>Hacim</th><th>Birim</th></tr>
  <tr>
    <td>Domates</td><td>Salka</td><td>Geleneksel/Konvansiyonel</td>
    <td>18,40</td><td>1.250</td><td>Kg</td>
  </tr>
  <tr>
    <td>Salatalık</td><td>Sera</td><td>Geleneksel/Konvansiyonel</td>
    <td>11,75</td><td>820</td><td>Kg</td>
  </tr>
  <tr>
    <td>Biber</td><td>Çarliston</td><td>Organik Tarım</td>
    <td>29,50</td><td>—</td><td>Kg</td>
  </tr>
  <tr class="pager">
    <td><a href="javascript:__doPostBack('ctl00$ctl37$g_abc_123$gvFiyatlar','Page$1')">1</a></td>
    <td><a href="javascript:__doPostBack('ctl00$ctl37$g_abc_123$gvFiyatlar','Page$2')">2</a></td>
    <td><a href="javascript:__doPostBack('ctl00$ctl37$g_abc_123$gvFiyatlar','Page$3')">3</a></td>
    <td><a href="javascript:__doPostBack('ctl00$ctl37$g_abc_123$gvFiyatlar','Page$4')">4</a></td>
    <td><a href="javascript:__doPostBack('ctl00$ctl37$g_abc_123$gvFiyatlar','Page$5')">5</a></td>
    <td><a href="javascript:__doPostBack('ctl00$ctl37$g_abc_123$gvFiyatlar','Page$6')">6</a></td>
  </tr>
  <tr><td>only one cell</td></tr>
</table>
</form>
</body></html>
"""


class TestParseTable:
    def test_extracts_data_rows_only(self) -> None:
        rows = _parse_table(SAMPLE_TABLE_HTML)
        assert len(rows) == 3  # pager row + 1-cell row both filtered
        assert rows[0] == {
            "product_name": "Domates",
            "product_variety": "Salka",
            "product_category": "Geleneksel/Konvansiyonel",
            "average_price": "18,40",
            "transaction_volume": "1.250",
            "unit_name": "Kg",
        }

    def test_filters_pager_rows_even_without_doPostBack(self) -> None:
        # Some renders strip the JS and leave plain digit cells.
        html = """
        <table id="gvFiyatlar">
          <tr><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td></tr>
          <tr><td>Domates</td><td>Salka</td><td>X</td><td>18,40</td><td>1.250</td><td>Kg</td></tr>
        </table>
        """
        rows = _parse_table(html)
        assert len(rows) == 1
        assert rows[0]["product_name"] == "Domates"

    def test_drops_rows_whose_product_name_is_purely_numeric(self) -> None:
        # A row may have 6 non-numeric cells overall but a digit-only product name
        # (paginator residue). Filter it out before the dedup constraint hits.
        html = """
        <table id="gvFiyatlar">
          <tr><td>12345678910</td><td>Cins</td><td>Tür</td><td>10,00</td><td>5</td><td>Kg</td></tr>
          <tr><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td></tr>
          <tr><td>Domates</td><td>Salka</td><td>X</td><td>18,40</td><td>1.250</td><td>Kg</td></tr>
        </table>
        """
        rows = _parse_table(html)
        assert [r["product_name"] for r in rows] == ["Domates"]

    def test_drops_rows_with_empty_or_punctuation_only_name(self) -> None:
        html = """
        <table id="gvFiyatlar">
          <tr><td></td><td>x</td><td>y</td><td>1</td><td>2</td><td>Kg</td></tr>
          <tr><td>—</td><td>x</td><td>y</td><td>1</td><td>2</td><td>Kg</td></tr>
          <tr><td>Domates</td><td>Salka</td><td>X</td><td>18,40</td><td>1.250</td><td>Kg</td></tr>
        </table>
        """
        rows = _parse_table(html)
        assert [r["product_name"] for r in rows] == ["Domates"]

    def test_returns_empty_when_table_missing(self) -> None:
        assert _parse_table("<html><body>no table</body></html>") == []


class TestExtractBulletinDate:
    def test_parses_turkish_date_format(self) -> None:
        d = HalGovTrScraper._extract_bulletin_date(SAMPLE_TABLE_HTML)
        assert d == date(2026, 5, 11)

    def test_returns_none_when_no_date_present(self) -> None:
        assert HalGovTrScraper._extract_bulletin_date("<html>no date here</html>") is None


class TestExtractHiddenFields:
    def test_picks_up_only_known_aspnet_fields(self) -> None:
        fields = _extract_hidden_fields(SAMPLE_TABLE_HTML)
        assert fields == {
            "__VIEWSTATE": "VIEWSTATE_TOKEN",
            "__VIEWSTATEGENERATOR": "GEN_TOKEN",
            "__EVENTVALIDATION": "VALIDATION_TOKEN",
        }

    def test_extracts_fields_from_async_delta_format(self) -> None:
        delta = (
            "10|hiddenField|__VIEWSTATE|FRESH_VS_TOKEN|"
            "8|hiddenField|__VIEWSTATEGENERATOR|NEW_GEN|"
            "12|hiddenField|__EVENTVALIDATION|FRESH_EV|"
        )
        fields = _extract_hidden_fields(delta)
        assert fields["__VIEWSTATE"] == "FRESH_VS_TOKEN"
        assert fields["__VIEWSTATEGENERATOR"] == "NEW_GEN"
        assert fields["__EVENTVALIDATION"] == "FRESH_EV"


class TestExtractGridId:
    def test_finds_gridview_id_containing_gvFiyatlar(self) -> None:
        html = (
            '<a href="#" onclick="'
            "javascript:__doPostBack('ctl00$ctl37$g_xyz$gvFiyatlar','Page$2')"
            '">2</a>'
        )
        assert _extract_grid_id(html) == "ctl00$ctl37$g_xyz$gvFiyatlar"

    def test_returns_none_when_no_grid_link(self) -> None:
        assert _extract_grid_id("<html><body>nothing here</body></html>") is None


class TestDiscoverTotalPages:
    def test_returns_max_page_number_present_in_postback_links(self) -> None:
        html = "Page$1 Page$2 Page$3 Page$10 Page$5"
        assert _discover_total_pages(html) == 10

    def test_defaults_to_one_when_no_postback_links(self) -> None:
        assert _discover_total_pages("<html>no pagination</html>") == 1


class TestExtractHtml:
    def test_passes_through_plain_html(self) -> None:
        html = "<html><body><p>hello</p></body></html>"
        assert _extract_html(html) == html

    def test_unwraps_update_panel_delta_format(self) -> None:
        # Delta segments: <len>|<type>|<id>|<content>
        # Compose: an updatePanel segment with HTML, plus a hiddenField segment.
        panel_content = "<div><table id='gvFiyatlar'><tr><td>x</td></tr></table></div>"
        delta = (
            f"{len(panel_content)}|updatePanel|grid|{panel_content}|5|hiddenField|__VIEWSTATE|abc|"
        )
        out = _extract_html(delta)
        assert "gvFiyatlar" in out


class TestRowToPrice:
    def test_maps_parsed_row_to_product_price(self) -> None:
        row = {
            "product_name": "Domates",
            "product_variety": "Salka",
            "product_category": "Geleneksel/Konvansiyonel",
            "average_price": "18,40",
            "transaction_volume": "1.250",
            "unit_name": "Kg",
        }
        bulletin_date = date(2026, 5, 11)
        p = HalGovTrScraper._row_to_price(row, bulletin_date)
        assert p.city_name == NATIONAL_CITY_NAME
        assert p.bulletin_date == bulletin_date
        assert p.product_name == "Domates"
        assert p.product_variety == "Salka"
        assert p.product_category == "Geleneksel/Konvansiyonel"
        assert p.average_price == Decimal("18.40")
        assert p.transaction_volume == 1250
        assert p.unit_name == "Kg"

    def test_blank_variety_and_category_become_none(self) -> None:
        row = {
            "product_name": "X",
            "product_variety": "",
            "product_category": "",
            "average_price": "1",
            "transaction_volume": "",
            "unit_name": "Adet",
        }
        p = HalGovTrScraper._row_to_price(row, date(2026, 5, 11))
        assert p.product_variety is None
        assert p.product_category is None
        assert p.transaction_volume is None
