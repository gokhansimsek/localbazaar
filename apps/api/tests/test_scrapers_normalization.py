"""Unit tests for numeric normalization used by the hal.gov.tr scraper."""

from __future__ import annotations

from decimal import Decimal

import pytest

from local_bazaar.scrapers.hal_gov_tr import (
    _normalize_number,
    _to_decimal,
    _to_int,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234,56", "1234.56"),
        ("12,5", "12.5"),
        ("0", "0"),
        ("\xa01.000,00", "1000.00"),
        (" 250,00 ", "250.00"),
        ("", ""),
    ],
)
def test_normalize_number_handles_tr_thousands_and_decimal(raw: str, expected: str) -> None:
    assert _normalize_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234,56", Decimal("1234.56")),
        ("0,01", Decimal("0.01")),
        ("125", Decimal("125")),
        ("0", Decimal("0")),
    ],
)
def test_to_decimal_parses_turkish_format(raw: str, expected: Decimal) -> None:
    assert _to_decimal(raw) == expected


@pytest.mark.parametrize("garbage", ["abc", "", "—", " ? ", "1,2,3,4"])
def test_to_decimal_returns_zero_on_unparseable(garbage: str) -> None:
    assert _to_decimal(garbage) == Decimal(0)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12.345", 12345),
        ("0", 0),
        ("1.000.000", 1000000),
        ("-50", -50),
        ("0,9", 0),  # rounded toward zero (drop decimal portion)
    ],
)
def test_to_int_strips_decimal_part(raw: str, expected: int) -> None:
    assert _to_int(raw) == expected


@pytest.mark.parametrize("garbage", ["", "abc", "—", " ? "])
def test_to_int_returns_none_on_unparseable(garbage: str) -> None:
    assert _to_int(garbage) is None
