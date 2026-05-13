"""Unit tests for the bazaar-locations scraper (HTML parsing + normalization only)."""

from __future__ import annotations

import pytest

from local_bazaar.scrapers.bazaar_locations import (
    _extract_guid_prefix,
    _extract_hidden_fields,
    _extract_select_options,
    _normalize_days,
    _normalize_market_name,
    _parse_markets,
    to_title_case_tr,
)

SAMPLE_FORM_HTML = """
<html><body>
<input type="hidden" name="__VIEWSTATE" value="VS" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="GEN" />
<input type="hidden" name="__EVENTVALIDATION" value="EV" />

<select name="ctl00$ctl37$g_abcdef0123456789$ddlIl" id="ctl00_ctl37_g_abcdef0123456789_ddlIl">
  <option value="0">İl Seçiniz</option>
  <option value="34">İstanbul</option>
  <option value="06">Ankara</option>
</select>

<select id="ctl00_ctl37_g_abcdef0123456789_ddlIlce">
  <option value="0">Tümü</option>
  <option value="1">Kadıköy</option>
</select>

<select id="ctl00_ctl37_g_abcdef0123456789_ddlPazarTuru">
  <option value="0">Tümü</option>
  <option value="9">Semt Pazarı</option>
  <option value="10">Üretici Pazarı</option>
</select>
</body></html>
"""

SAMPLE_RESULTS = """
<html><body>
<table id="ctl00_g_xx_gvListe" class="gridView">
  <tr><th>Pazar Adı</th><th>Türü</th><th>Adres</th><th>İl</th><th>İlçe</th><th>Semt</th><th>Kuruluş Günleri</th></tr>
  <tr>
    <td>MURATBEY SEMT PAZARI (KÖYLÜ PAZARI BÖLÜMÜ)</td>
    <td>Semt Pazarı</td><td>Muratbey Mah. Atatürk Cad.</td>
    <td>İSTANBUL</td><td>BÜYÜKÇEKMECE</td><td>MERKEZ</td>
    <td>Pzt,Pazar</td>
  </tr>
  <tr>
    <td>MURATBEY SEMT PAZARI (BALIK BÖLÜMÜ)</td>
    <td>Semt Pazarı</td><td>Muratbey Mah. Atatürk Cad.</td>
    <td>İSTANBUL</td><td>BÜYÜKÇEKMECE</td><td>MERKEZ</td>
    <td>Pzt,Pazar</td>
  </tr>
  <tr>
    <td>ADANA KOOP.SEMT PAZARI</td>
    <td>Semt Pazarı</td><td>B.Evleri Mh .Çoban Yurtçu Blv.</td>
    <td>ADANA</td><td>ÇUKUROVA</td><td>MERKEZ</td>
    <td>Salı,Çrş</td>
  </tr>
  <tr><td>only one cell</td></tr>
</table>
</body></html>
"""


class TestExtractHiddenFields:
    def test_returns_only_known_aspnet_fields(self) -> None:
        out = _extract_hidden_fields(SAMPLE_FORM_HTML)
        assert out == {
            "__VIEWSTATE": "VS",
            "__VIEWSTATEGENERATOR": "GEN",
            "__EVENTVALIDATION": "EV",
        }


class TestExtractGuidPrefix:
    def test_finds_session_prefix(self) -> None:
        assert _extract_guid_prefix(SAMPLE_FORM_HTML) == "ctl00$ctl37$g_abcdef0123456789"

    def test_returns_none_when_no_prefix(self) -> None:
        assert _extract_guid_prefix("<html>nothing</html>") is None


class TestExtractSelectOptions:
    def test_provinces_skip_placeholder(self) -> None:
        out = _extract_select_options(SAMPLE_FORM_HTML, "ddlIl")
        assert out == [("34", "İstanbul"), ("06", "Ankara")]

    def test_market_type_select_options_use_codes(self) -> None:
        out = _extract_select_options(SAMPLE_FORM_HTML, "ddlPazarTuru")
        # "Tümü" with value 0 is the placeholder — filtered.
        assert out == [("9", "Semt Pazarı"), ("10", "Üretici Pazarı")]


class TestParseMarkets:
    def test_extracts_seven_column_rows(self) -> None:
        rows = _parse_markets(SAMPLE_RESULTS)
        assert len(rows) == 3
        first = rows[0]
        assert first["name"] == "MURATBEY SEMT PAZARI (KÖYLÜ PAZARI BÖLÜMÜ)"
        assert first["type_label"] == "Semt Pazarı"
        assert first["address"].startswith("Muratbey Mah")
        assert first["province"] == "İSTANBUL"
        assert first["district"] == "BÜYÜKÇEKMECE"
        assert first["neighborhood"] == "MERKEZ"
        assert first["days_raw"] == "Pzt,Pazar"

    def test_returns_empty_when_no_gvListe(self) -> None:
        assert _parse_markets("<html><body>nothing</body></html>") == []


class TestNormalizeMarketName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("MURATBEY SEMT PAZARI (BALIK BÖLÜMÜ)", "Muratbey Semt Pazarı"),
            ("MURATBEY SEMT PAZARI (KÖYLÜ PAZARI BÖLÜMÜ)", "Muratbey Semt Pazarı"),
            ("MURATBEY SEMT PAZARI (A) (B)", "Muratbey Semt Pazarı"),
            ("GÜZELYALI KAPALI SEMT PAZARI", "Güzelyalı Kapalı Semt Pazarı"),
            ("  spaced   pazar (suffix)  ", "Spaced Pazar"),
            ("MURATBEY KPY", "Muratbey Kapalı Pazar Yeri"),
            ("MURATBEY KPY (BALIK BÖLÜMÜ)", "Muratbey Kapalı Pazar Yeri"),
            ("kpy alani", "Kapalı Pazar Yeri Alani"),  # whole-word case-insensitive
        ],
    )
    def test_strips_parens_expands_abbrev_and_title_cases(self, raw: str, expected: str) -> None:
        assert _normalize_market_name(raw) == expected


class TestToTitleCaseTr:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("İSTANBUL", "İstanbul"),
            ("ÇUKUROVA", "Çukurova"),
            ("ADANA KOOP.SEMT PAZARI", "Adana Koop.Semt Pazarı"),
            ("GÜZELYALI MAH. 81163 SK.", "Güzelyalı Mah. 81163 Sk."),
            ("ŞANLIURFA", "Şanlıurfa"),
            ("kahraman maraş", "Kahraman Maraş"),
            ("", ""),
        ],
    )
    def test_turkish_aware_title_case(self, raw: str, expected: str) -> None:
        assert to_title_case_tr(raw) == expected


class TestNormalizeDays:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Pzt,Pazar", "Pazartesi,Pazar"),
            ("Salı,Çrş", "Salı,Çarşamba"),
            ("Prş,Cuma", "Perşembe,Cuma"),
            ("Cmt", "Cumartesi"),
            ("pzt , çar", "Pazartesi,Çarşamba"),
            ("Pazartesi", "Pazartesi"),  # already-canonical input passes through
        ],
    )
    def test_expands_short_forms_to_full_turkish(self, raw: str, expected: str) -> None:
        assert _normalize_days(raw) == expected

    def test_keeps_unknown_token_verbatim(self) -> None:
        assert _normalize_days("Hafta sonu") == "Hafta sonu"

    def test_empty_returns_none(self) -> None:
        assert _normalize_days("") is None
        assert _normalize_days("   ") is None
