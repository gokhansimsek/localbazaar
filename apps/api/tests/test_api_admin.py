"""Integration tests for the hidden admin suggestion-review endpoints.

Skipped automatically when ``TEST_DATABASE_URL`` is not set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import local_bazaar.api.admin as admin_module
from local_bazaar.config import settings
from local_bazaar.db import get_session
from local_bazaar.main import app
from local_bazaar.models import (
    District,
    Market,
    MarketType,
    PlaceSuggestion,
    Province,
    SuggestionType,
    User,
)
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.asyncio]

TOKEN = "test-admin-secret"
HEADERS = {"X-Admin-Token": TOKEN}


async def _seed(session: AsyncSession) -> dict[str, int]:
    """Seed a province, district, market, and a user.

    Args:
        session: Test DB session.

    Returns:
        A dict of the seeded ``province``/``district``/``market``/``user`` ids.
    """
    province = Province(slug="istanbul", name="İstanbul", plate_code=34)
    session.add(province)
    await session.flush()
    district = District(province_id=province.id or 0, slug="kadikoy", name="Kadıköy")
    session.add(district)
    await session.flush()
    market = Market(
        district_id=district.id or 0,
        market_type=MarketType.SEMT_PAZARI,
        name="Salı Pazarı",
    )
    session.add(market)
    user = User(first_name="Ada", last_name="Yılmaz", email="ada@example.com")
    session.add(user)
    await session.flush()
    await session.commit()
    return {
        "province": province.id or 0,
        "district": district.id or 0,
        "market": market.id or 0,
        "user": user.id or 0,
    }


async def _add_suggestion(session: AsyncSession, **kwargs: object) -> int:
    """Insert a PlaceSuggestion and return its id."""
    suggestion = PlaceSuggestion(**kwargs)  # type: ignore[arg-type]
    session.add(suggestion)
    await session.flush()
    sid = suggestion.id or 0
    await session.commit()
    return sid


def _override_session(
    session: AsyncSession,
) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _dep() -> AsyncIterator[AsyncSession]:
        yield session

    return _dep


async def test_admin_requires_configured_token(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", "")  # not configured
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/suggestions", headers=HEADERS)
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


async def test_admin_rejects_bad_token(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r_missing = await ac.get("/api/admin/suggestions")
            r_wrong = await ac.get("/api/admin/suggestions", headers={"X-Admin-Token": "nope"})
        assert r_missing.status_code == 401
        assert r_wrong.status_code == 401
    finally:
        app.dependency_overrides.clear()


async def test_admin_lists_pending(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    ids = await _seed(db_session)
    await _add_suggestion(
        db_session,
        user_id=ids["user"],
        suggestion_type=SuggestionType.UPDATE,
        market_id=ids["market"],
        explanation="Gün yanlış",
    )
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/suggestions", headers=HEADERS)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["email"] == "ada@example.com"
        assert rows[0]["market_name"] == "Salı Pazarı"
    finally:
        app.dependency_overrides.clear()


async def test_approve_add_with_known_district_creates_market(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    ids = await _seed(db_session)
    sid = await _add_suggestion(
        db_session,
        user_id=ids["user"],
        suggestion_type=SuggestionType.ADD,
        proposed_name="Yeni Cumartesi Pazarı",
        proposed_market_type="semt_pazari",
        district_id=ids["district"],
        latitude=40.99,
        longitude=29.03,
        explanation="Eksik pazar",
    )
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/admin/suggestions/{sid}/approve", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"
        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM markets WHERE name = 'Yeni Cumartesi Pazarı'")
            )
        ).scalar_one()
        assert count == 1
    finally:
        app.dependency_overrides.clear()


async def test_approve_add_resolves_district_via_reverse_geocode(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", TOKEN)

    async def _fake_reverse(lat: float, lng: float, api_key: str | None = None) -> tuple[str, str]:
        return "İstanbul", "Kadıköy"

    monkeypatch.setattr(admin_module, "reverse_geocode_admin_areas", _fake_reverse)
    ids = await _seed(db_session)
    sid = await _add_suggestion(
        db_session,
        user_id=ids["user"],
        suggestion_type=SuggestionType.ADD,
        proposed_name="Pin Çözümlü Pazar",
        latitude=40.99,
        longitude=29.03,
        explanation="konumdan çözülecek",
    )
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/admin/suggestions/{sid}/approve", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        linked = (
            await db_session.execute(
                text("SELECT district_id FROM markets WHERE name = 'Pin Çözümlü Pazar'")
            )
        ).scalar_one()
        assert linked == ids["district"]
    finally:
        app.dependency_overrides.clear()


async def test_approve_update_applies_coordinates(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    ids = await _seed(db_session)
    sid = await _add_suggestion(
        db_session,
        user_id=ids["user"],
        suggestion_type=SuggestionType.UPDATE,
        market_id=ids["market"],
        latitude=41.5,
        longitude=29.5,
        explanation="Konum düzeltmesi",
    )
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(f"/api/admin/suggestions/{sid}/approve", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        lat = (
            await db_session.execute(
                text("SELECT latitude FROM markets WHERE id = :mid"), {"mid": ids["market"]}
            )
        ).scalar_one()
        assert float(lat) == pytest.approx(41.5)
    finally:
        app.dependency_overrides.clear()


async def test_reject_marks_rejected(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    ids = await _seed(db_session)
    sid = await _add_suggestion(
        db_session,
        user_id=ids["user"],
        suggestion_type=SuggestionType.UPDATE,
        market_id=ids["market"],
        explanation="spam",
    )
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/admin/suggestions/{sid}/reject",
                headers=HEADERS,
                json={"note": "duplicate"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"
        # A rejected suggestion is no longer pending — second action conflicts.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            again = await ac.post(f"/api/admin/suggestions/{sid}/approve", headers=HEADERS)
        assert again.status_code == 409
    finally:
        app.dependency_overrides.clear()
