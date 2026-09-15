"""Integration tests for the newsletter signup endpoint.

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
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.asyncio]


def _override_session(
    session: AsyncSession,
) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _dep() -> AsyncIterator[AsyncSession]:
        yield session

    return _dep


async def _post(session: AsyncSession, payload: dict[str, object]) -> tuple[int, object]:
    app.dependency_overrides[get_session] = _override_session(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/newsletter", json=payload)
        return resp.status_code, resp.json()
    finally:
        app.dependency_overrides.clear()


async def _emails(session: AsyncSession) -> list[str]:
    rows = await session.execute(text("SELECT email FROM newsletter_subscribers ORDER BY id"))
    return [str(r[0]) for r in rows]


async def test_subscribe_stores_normalized_email(db_session: AsyncSession) -> None:
    status, body = await _post(db_session, {"email": "  Ada@Example.com ", "consent": True})
    assert status == 200
    assert body == {"status": "subscribed"}
    assert await _emails(db_session) == ["ada@example.com"]


async def test_repeat_subscribe_is_idempotent(db_session: AsyncSession) -> None:
    first, _ = await _post(db_session, {"email": "ada@example.com", "consent": True})
    second, body = await _post(db_session, {"email": "ADA@example.com", "consent": True})
    assert (first, second) == (200, 200)
    assert body == {"status": "subscribed"}
    assert await _emails(db_session) == ["ada@example.com"]


async def test_consent_is_required(db_session: AsyncSession) -> None:
    status, _ = await _post(db_session, {"email": "ada@example.com", "consent": False})
    assert status == 400
    assert await _emails(db_session) == []


async def test_honeypot_rejects_bots(db_session: AsyncSession) -> None:
    status, _ = await _post(
        db_session, {"email": "bot@example.com", "consent": True, "website": "http://spam"}
    )
    assert status == 400
    assert await _emails(db_session) == []


async def test_invalid_email_is_rejected(db_session: AsyncSession) -> None:
    status, _ = await _post(db_session, {"email": "not-an-email", "consent": True})
    assert status == 422
    assert await _emails(db_session) == []
