"""Shared pytest fixtures.

Most scraper / parsing tests are pure unit tests with no DB. Integration tests that
hit the database require a reachable PostgreSQL — set the ``TEST_DATABASE_URL`` env
var. If it is missing, integration tests are skipped automatically.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from local_bazaar import models
from local_bazaar.db import metadata as prices_metadata

# Side-effect import: referencing `models` registers every SQLModel class with
# SQLModel.metadata so the test DB schema can be created.
_ = models


def _test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


requires_db = pytest.mark.skipif(
    _test_db_url() is None,
    reason="TEST_DATABASE_URL not set — skipping DB integration tests.",
)


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Event-loop policy for async tests.

    On Windows, psycopg's async mode is incompatible with the default
    ``ProactorEventLoop``, so use a selector-based policy (mirrors the fix in
    ``migrations/env.py``). Other platforms keep the default policy.

    Returns:
        The event-loop policy pytest-asyncio should use for the session.
    """
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Async SQLAlchemy session bound to a test database.

    Creates the registry tables (cities, scrape_runs) for each test and drops them
    after. Per-city ``prices_*`` tables are created on demand by the code under test.
    """
    url = _test_db_url()
    if url is None:
        pytest.skip("TEST_DATABASE_URL not set")

    engine = create_async_engine(url, echo=False, future=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        async with SessionLocal() as session:
            yield session
    finally:
        async with engine.begin() as conn:
            # Drop everything created in this test (registry + per-city tables).
            await conn.run_sync(prices_metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()
