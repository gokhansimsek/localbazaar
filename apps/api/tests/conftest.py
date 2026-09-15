"""Shared pytest fixtures.

Most scraper / parsing tests are pure unit tests with no DB. Integration tests that
hit the database require a reachable PostgreSQL — set the ``TEST_DATABASE_URL`` env
var. If it is missing, integration tests are skipped automatically.
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from local_bazaar import models
from local_bazaar.db import metadata as prices_metadata

# Side-effect import: referencing `models` registers every SQLModel class with
# SQLModel.metadata so the test DB schema can be created.
_ = models

# ``products`` is deliberately NOT an SQLModel class (see local_bazaar/db.py) —
# it only exists via the raw DDL in migration 0006_products, which nothing in
# this fixture otherwise runs. Mirror that DDL here so tests that exercise
# `ensure_city_table()` / `upsert_prices()` (whose per-city tables FK-reference
# `products(id)`) have something to reference. Keep this in sync with
# `migrations/versions/0006_products.py` if that table's shape ever changes.
_CREATE_PRODUCTS_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    variety TEXT,
    category TEXT,
    unit_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
_CREATE_PRODUCTS_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_full ON products (
    name, COALESCE(variety, ''), COALESCE(category, ''), unit_name
)
"""


async def _create_products_table(engine: AsyncEngine) -> None:
    """Create the ``products`` table used by per-city price tables' FK.

    Args:
        engine: The test database engine.
    """
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_PRODUCTS_SQL))
        await conn.execute(text(_CREATE_PRODUCTS_INDEX_SQL))


def _test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


requires_db = pytest.mark.skipif(
    _test_db_url() is None,
    reason="TEST_DATABASE_URL not set — skipping DB integration tests.",
)


def pytest_configure(config: pytest.Config) -> None:
    """Use a selector event loop on Windows so psycopg async tests can run.

    Psycopg's async driver is incompatible with the default ``ProactorEventLoop``
    on Windows. Alembic applies the same workaround in ``migrations/env.py`` via
    ``asyncio.run(..., loop_factory=...)``; pytest-asyncio 1.x still routes tests
    through the (deprecated) policy API, so we install ``WindowsSelectorEventLoopPolicy``
    before the session starts.

    Args:
        config: Pytest configuration object (unused; required by hook signature).
    """
    _ = config
    if sys.platform != "win32":
        return

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        policy = asyncio.WindowsSelectorEventLoopPolicy()  # pyright: ignore[reportAttributeAccessIssue]
        asyncio.set_event_loop_policy(policy)  # pyright: ignore[reportAttributeAccessIssue]


@pytest.fixture
def allow_robots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the ``robots.txt`` check performed by ``scrapers.base.fetch_with_retry``.

    Per-city scraper tests exercise ``fetch_with_retry`` against respx-mocked
    endpoints. Without this fixture, each such test would also need to mock
    that origin's ``<scheme>://<host>/robots.txt`` — an unrelated
    implementation detail of the politeness policy in ``scrapers/base.py`` —
    or fall over with respx's "not mocked" error. This stubs
    ``local_bazaar.scrapers.base.is_allowed`` to always return ``True`` for
    the duration of the test.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
    """

    async def _always_allowed(url: str, user_agent: str | None = None) -> bool:
        return True

    monkeypatch.setattr("local_bazaar.scrapers.base.is_allowed", _always_allowed)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Async SQLAlchemy session bound to a test database.

    Creates the registry tables (cities, scrape_runs, products, ...) for each
    test and drops them after. Per-city ``prices_*`` tables are created on
    demand by the code under test.
    """
    url = _test_db_url()
    if url is None:
        pytest.skip("TEST_DATABASE_URL not set")

    engine = create_async_engine(url, echo=False, future=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    await _create_products_table(engine)

    try:
        async with SessionLocal() as session:
            yield session
    finally:
        async with engine.begin() as conn:
            # Drop everything created in this test (registry + per-city tables).
            # Per-city prices_* tables FK-reference products, so they must go
            # first; SQLModel's tables have no such dependency on products.
            await conn.run_sync(prices_metadata.drop_all)
            await conn.execute(text("DROP TABLE IF EXISTS products CASCADE"))
            await conn.run_sync(SQLModel.metadata.drop_all)
        await engine.dispose()
