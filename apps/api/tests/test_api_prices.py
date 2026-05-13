"""Integration tests for the FastAPI price endpoints.

These tests stand up the real app and an actual PostgreSQL DB. They are skipped
automatically when ``TEST_DATABASE_URL`` is not set, so the unit-test suite stays
runnable in any environment.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.db import (
    ensure_city_table,
    get_session,
    prices_table_name,
)
from local_bazaar.main import app
from local_bazaar.models import City, CitySourceType
from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.asyncio]


async def _seed(session: AsyncSession) -> None:
    """Seed two cities and a few price rows in each."""
    session.add(
        City(
            slug="national",
            name="National",
            source_type=CitySourceType.HAL_GOV_TR,
            source_url="https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx",
            enabled=True,
        )
    )
    session.add(
        City(
            slug="istanbul",
            name="Istanbul",
            source_type=CitySourceType.CITY_SITE,
            source_url="https://example.test/istanbul",
            enabled=True,
        )
    )
    await session.commit()
    await ensure_city_table(session, "national")
    await ensure_city_table(session, "istanbul")

    for slug, samples in (
        (
            "national",
            [
                (
                    date(2026, 5, 10),
                    "Domates",
                    "Salka",
                    "Geleneksel/Konvansiyonel",
                    "17.50",
                    1000,
                    "Kg",
                ),
                (
                    date(2026, 5, 11),
                    "Domates",
                    "Salka",
                    "Geleneksel/Konvansiyonel",
                    "18.40",
                    1250,
                    "Kg",
                ),
                (
                    date(2026, 5, 11),
                    "Salatalık",
                    "Sera",
                    "Geleneksel/Konvansiyonel",
                    "11.75",
                    820,
                    "Kg",
                ),
            ],
        ),
        (
            "istanbul",
            [
                (
                    date(2026, 5, 11),
                    "Domates",
                    "Salka",
                    "Geleneksel/Konvansiyonel",
                    "19.10",
                    600,
                    "Kg",
                ),
            ],
        ),
    ):
        table = prices_table_name(slug)
        for row in samples:
            await session.execute(
                text(
                    f"""
                    INSERT INTO {table}
                    (bulletin_date, product_name, product_variety, product_category,
                     average_price, transaction_volume, unit_name)
                    VALUES (:d, :n, :v, :c, :p, :h, :u)
                    """
                ),
                {
                    "d": row[0],
                    "n": row[1],
                    "v": row[2],
                    "c": row[3],
                    "p": Decimal(row[4]),
                    "h": row[5],
                    "u": row[6],
                },
            )
    await session.commit()


def _override_session(
    session: AsyncSession,
) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _dep() -> AsyncIterator[AsyncSession]:
        yield session

    return _dep


async def test_list_cities_returns_enabled_only(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/cities")
        assert resp.status_code == 200
        slugs = [c["slug"] for c in resp.json()]
        assert slugs == sorted(slugs)  # ordered by name
        assert {"national", "istanbul"}.issubset(set(slugs))
    finally:
        app.dependency_overrides.clear()


async def test_city_prices_returns_latest_when_no_date(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/cities/national/prices")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2  # only May 11 rows
        assert {r["product_name"] for r in rows} == {"Domates", "Salatalık"}
        assert all(r["bulletin_date"] == "2026-05-11" for r in rows)
    finally:
        app.dependency_overrides.clear()


async def test_city_prices_with_specific_date(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/cities/national/prices?date=2026-05-10")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["product_name"] == "Domates"
        assert rows[0]["average_price"] == "17.5000"
    finally:
        app.dependency_overrides.clear()


async def test_city_prices_unknown_slug_returns_404(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/cities/atlantis/prices")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_product_history_unions_across_cities(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/products/Domates/history")
        assert resp.status_code == 200
        points = resp.json()
        # Domates has 2 rows in national + 1 in istanbul = 3.
        assert len(points) == 3
        cities = {p["city_slug"] for p in points}
        assert cities == {"national", "istanbul"}
    finally:
        app.dependency_overrides.clear()


async def test_product_history_filters_to_one_city(db_session: AsyncSession) -> None:
    await _seed(db_session)
    app.dependency_overrides[get_session] = _override_session(db_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/products/Domates/history?city=istanbul")
        assert resp.status_code == 200
        points = resp.json()
        assert len(points) == 1
        assert points[0]["city_slug"] == "istanbul"
    finally:
        app.dependency_overrides.clear()


async def test_healthz() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_test_db_url_is_set_when_required() -> None:
    # Sanity check: the marker should have skipped us if it weren't set.
    assert os.environ.get("TEST_DATABASE_URL") is not None
