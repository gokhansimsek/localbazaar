"""Unit tests for the Turkish-aware city slug helper."""

from __future__ import annotations

import pytest
from sqlalchemy import UniqueConstraint

from local_bazaar.db import city_slug, prices_table, prices_table_name


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Istanbul", "istanbul"),
        ("İstanbul", "istanbul"),
        ("Ankara", "ankara"),
        ("Şanlıurfa", "sanliurfa"),
        ("Şanliurfa", "sanliurfa"),
        ("Çorum", "corum"),
        ("Gümüşhane", "gumushane"),
        ("Niğde", "nigde"),
        ("Diyarbakır", "diyarbakir"),
        ("  Bursa  ", "bursa"),
        ("National", "national"),
    ],
)
def test_city_slug_folds_turkish_chars(name: str, expected: str) -> None:
    assert city_slug(name) == expected


def test_city_slug_collapses_separators() -> None:
    assert city_slug("Kahraman Maraş") == "kahraman_maras"
    assert city_slug("K.Maraş - merkez") == "k_maras_merkez"


def test_city_slug_strips_leading_trailing_underscores() -> None:
    assert city_slug("--İzmir--") == "izmir"


def test_prices_table_name_uses_slug_prefix() -> None:
    assert prices_table_name("istanbul") == "prices_istanbul"
    assert prices_table_name("national") == "prices_national"


def test_prices_table_is_cached_per_slug() -> None:
    t1 = prices_table("ankara")
    t2 = prices_table("ankara")
    assert t1 is t2


def test_prices_table_has_expected_columns() -> None:
    t = prices_table("test_cols")
    column_names = {c.name for c in t.columns}
    assert column_names == {
        "id",
        "bulletin_date",
        "product_name",
        "product_variety",
        "product_category",
        "average_price",
        "transaction_volume",
        "unit_name",
        "last_updated",
    }


def test_prices_table_unique_constraint_includes_bulletin_and_product_attrs() -> None:
    t = prices_table("test_uniq")
    unique = next(c for c in t.constraints if isinstance(c, UniqueConstraint))
    cols = {c.name for c in unique.columns}
    assert cols == {
        "bulletin_date",
        "product_name",
        "product_variety",
        "product_category",
        "unit_name",
    }
