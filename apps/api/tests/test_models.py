"""Unit tests for ORM model construction (no DB session required)."""

from __future__ import annotations

from local_bazaar.models import (
    City,
    CitySourceType,
    ScrapeRun,
    ScrapeRunStatus,
)


def test_city_defaults() -> None:
    c = City(slug="istanbul", name="Istanbul")
    assert c.source_type == CitySourceType.HAL_GOV_TR
    assert c.enabled is True
    assert c.source_url is None


def test_city_source_type_enum_values() -> None:
    assert CitySourceType.HAL_GOV_TR.value == "hal_gov_tr"
    assert CitySourceType.CITY_SITE.value == "city_site"


def test_scrape_run_defaults() -> None:
    run = ScrapeRun(scraper="hal_gov_tr")
    assert run.status == ScrapeRunStatus.OK
    assert run.rows_written == 0
    assert run.error is None
    assert run.city_slug is None
    assert run.bulletin_date is None


def test_scrape_run_status_enum_values() -> None:
    assert {s.value for s in ScrapeRunStatus} == {"ok", "partial", "failed"}
