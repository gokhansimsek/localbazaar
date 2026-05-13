"""Unit tests for the scheduler helpers (no real apscheduler instance)."""

from __future__ import annotations

from local_bazaar.scheduler import today_istanbul


def test_today_istanbul_returns_a_date() -> None:
    d = today_istanbul()
    # Type/sanity check — we don't pin a specific value because the test runs at any time.
    assert d.year >= 2026
    assert 1 <= d.month <= 12
    assert 1 <= d.day <= 31


# Note: integration tests for _safe_scrape() that exercise the actual DB live in
# tests/test_api_prices.py — they require TEST_DATABASE_URL. The scheduler logic
# itself is thin glue (apscheduler), so we lean on the integration coverage there.
