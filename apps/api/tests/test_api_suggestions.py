"""Integration tests for the place-suggestion endpoint.

Stand up the real app against an actual PostgreSQL DB. Skipped automatically
when ``TEST_DATABASE_URL`` is not set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.db import get_session
from local_bazaar.main import app
from local_bazaar.models import District, Market, MarketType, Province
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.asyncio]


async def _seed(session: AsyncSession) -> int:
    """Seed one province, district, and market.

    Args:
        session: Test DB session.

    Returns:
        The seeded market's id (used by update-suggestion tests).
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
    await session.flush()
    await session.commit()
    return market.id or 0


def _override_session(
    session: AsyncSession,
) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _dep() -> AsyncIterator[AsyncSession]:
        yield session

    return _dep


async def _count(session: AsyncSession, table: str) -> int:
    return int((await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one())


async def test_add_suggestion_creates_user_and_pending(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/suggestions",
                json={
                    "first_name": "Ada",
                    "last_name": "Yılmaz",
                    "email": "Ada@Example.com",
                    "user_province": "istanbul",
                    "user_district": "kadikoy",
                    "suggestion_type": "add",
                    "name": "Yeni Semt Pazarı",
                    "market_type": "semt_pazari",
                    "latitude": 40.99,
                    "longitude": 29.03,
                    "explanation": "Burada büyük bir pazar var.",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["id"] > 0
        assert await _count(db_session, "users") == 1
        assert await _count(db_session, "place_suggestions") == 1
        # Email is normalized to lowercase on the way in.
        email = (await db_session.execute(text("SELECT email FROM users"))).scalar_one()
        assert email == "ada@example.com"
    finally:
        app.dependency_overrides.clear()


async def test_repeat_email_reuses_user(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    payload = {
        "first_name": "Ada",
        "last_name": "Yılmaz",
        "email": "ada@example.com",
        "suggestion_type": "add",
        "name": "Pazar A",
        "latitude": 41.0,
        "longitude": 29.0,
        "explanation": "ilk öneri",
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r1 = await ac.post("/api/suggestions", json=payload)
            r2 = await ac.post(
                "/api/suggestions",
                json={**payload, "name": "Pazar B", "explanation": "ikinci öneri"},
            )
        assert r1.status_code == 200 and r2.status_code == 200
        assert await _count(db_session, "users") == 1  # deduped by email
        assert await _count(db_session, "place_suggestions") == 2
    finally:
        app.dependency_overrides.clear()


async def test_update_suggestion_references_market(db_session: AsyncSession) -> None:
    market_id = await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/suggestions",
                json={
                    "first_name": "Mert",
                    "last_name": "Demir",
                    "email": "mert@example.com",
                    "suggestion_type": "update",
                    "market_id": market_id,
                    "explanation": "Bu pazarın günü yanlış.",
                },
            )
        assert resp.status_code == 200, resp.text
        linked = (
            await db_session.execute(text("SELECT market_id FROM place_suggestions"))
        ).scalar_one()
        assert linked == market_id
    finally:
        app.dependency_overrides.clear()


async def test_update_requires_market_id(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/suggestions",
                json={
                    "first_name": "Mert",
                    "last_name": "Demir",
                    "email": "mert@example.com",
                    "suggestion_type": "update",
                    "explanation": "eksik market",
                },
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


async def test_add_requires_name_and_coords(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/suggestions",
                json={
                    "first_name": "Ada",
                    "last_name": "Yılmaz",
                    "email": "ada@example.com",
                    "suggestion_type": "add",
                    "name": "Adsız değil ama konumsuz",
                    "explanation": "koordinat yok",
                },
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


async def test_honeypot_rejected(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/suggestions",
                json={
                    "first_name": "Bot",
                    "last_name": "Spam",
                    "email": "bot@example.com",
                    "suggestion_type": "add",
                    "name": "Spam",
                    "latitude": 41.0,
                    "longitude": 29.0,
                    "explanation": "spam",
                    "website": "http://spam.example",
                },
            )
        assert resp.status_code == 400
        assert await _count(db_session, "place_suggestions") == 0
    finally:
        app.dependency_overrides.clear()


async def test_unknown_province_returns_404(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/suggestions",
                json={
                    "first_name": "Ada",
                    "last_name": "Yılmaz",
                    "email": "ada@example.com",
                    "user_province": "no-such-province",
                    "suggestion_type": "add",
                    "name": "Pazar",
                    "latitude": 41.0,
                    "longitude": 29.0,
                    "explanation": "il yok",
                },
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
