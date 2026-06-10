"""Async DB engine, session, and per-city table helpers.

Schema convention (see CLAUDE.md):
- One table per city named ``prices_<slug>`` (e.g. ``prices_national``, ``prices_istanbul``).
- Every per-city table has identical columns. The ``cities`` registry tracks which slugs exist.
- A ``prices_all`` SQL view UNION ALLs every registered table so cross-city queries don't need
  client-side fan-out. It is rebuilt whenever the city set changes.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from functools import cache

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from local_bazaar.config import settings

metadata = MetaData()

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# --- Slugging --------------------------------------------------------------

_TR_MAP = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def city_slug(name: str) -> str:
    """Compute a Turkish-aware ASCII slug for a city name.

    Args:
        name: The display name of the city (e.g. ``"İstanbul"``, ``"Şanlıurfa"``).

    Returns:
        A lowercase ASCII slug suitable for table names and URLs
        (``"istanbul"``, ``"sanliurfa"``).
    """
    lowered = name.translate(_TR_MAP).lower()
    return _SLUG_RE.sub("_", lowered).strip("_")


def prices_table_name(slug: str) -> str:
    """Build the per-city prices table name for a slug.

    Args:
        slug: The city slug as returned by :func:`city_slug`.

    Returns:
        The fully qualified table name, e.g. ``"prices_istanbul"``.
    """
    return f"prices_{slug}"


# --- Per-city table factory ------------------------------------------------


@cache
def prices_table(slug: str) -> Table:
    """Build (or return the cached) SQLAlchemy Table for a city's prices.

    Cached by slug so subsequent calls return the same Table object and
    SQLAlchemy's metadata stays consistent.

    Args:
        slug: The city slug whose prices table is needed.

    Returns:
        A :class:`sqlalchemy.Table` definition for ``prices_<slug>``.
    """
    name = prices_table_name(slug)
    return Table(
        name,
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("bulletin_date", Date, nullable=False, index=True),
        Column("product_name", Text, nullable=False, index=True),
        Column("product_variety", Text, nullable=True),
        Column("product_category", Text, nullable=True),
        Column("average_price", Numeric(12, 4), nullable=False),
        Column("transaction_volume", BigInteger, nullable=True),
        Column("unit_name", Text, nullable=False),
        # Phase 2: FK to products.id. Nullable until Phase 3 finishes
        # migrating scrapers/API to write/read this column exclusively.
        Column("product_id", BigInteger, nullable=True, index=True),
        Column(
            "last_updated",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
        UniqueConstraint(
            "bulletin_date",
            "product_name",
            "product_variety",
            "product_category",
            "unit_name",
            name=f"uq_{name}_bulletin_product",
        ),
    )


# --- DDL helpers (used by migrations and at runtime when a city is added) --


async def ensure_city_table(session: AsyncSession, slug: str) -> None:
    """Create ``prices_<slug>`` if it does not already exist.

    Idempotent — safe to call on every scrape. Also creates the supporting
    indexes on ``bulletin_date`` and ``product_name``.

    Args:
        session: An open async DB session.
        slug: The city slug to provision a table for.
    """
    table = prices_table(slug)
    await session.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {table.name} (
                id BIGSERIAL PRIMARY KEY,
                bulletin_date DATE NOT NULL,
                product_name TEXT NOT NULL,
                product_variety TEXT,
                product_category TEXT,
                average_price NUMERIC(12,4) NOT NULL,
                transaction_volume BIGINT,
                unit_name TEXT NOT NULL,
                product_id BIGINT REFERENCES products(id),
                last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_{table.name}_bulletin_product
                    UNIQUE (bulletin_date, product_name, product_variety, product_category, unit_name)
            )
            """
        )
    )
    # Defensive: an older deployment may have created the table before
    # product_id existed. Add it idempotently.
    await session.execute(
        text(
            f"ALTER TABLE {table.name} "
            f"ADD COLUMN IF NOT EXISTS product_id BIGINT REFERENCES products(id)"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{table.name}_bulletin_date ON {table.name} (bulletin_date)"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{table.name}_product_name ON {table.name} (product_name)"
        )
    )
    await session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS ix_{table.name}_product_id ON {table.name} (product_id)"
        )
    )


async def rebuild_prices_view(session: AsyncSession, slugs: list[str]) -> None:
    """Rebuild the ``prices_all`` view as a UNION ALL across every registered city table.

    Args:
        session: An open async DB session.
        slugs: All registered city slugs that should appear in the unioned view.
            If empty, the view is dropped.
    """
    if not slugs:
        await session.execute(text("DROP VIEW IF EXISTS prices_all"))
        return

    union_sql = "\nUNION ALL\n".join(
        f"SELECT '{s}'::text AS city_slug, * FROM {prices_table_name(s)}" for s in slugs
    )
    await session.execute(text("DROP VIEW IF EXISTS prices_all"))
    await session.execute(text(f"CREATE VIEW prices_all AS {union_sql}"))


# --- FastAPI dependency ----------------------------------------------------


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async DB session — used as a FastAPI dependency in route handlers.

    Yields:
        A session bound to the configured PostgreSQL engine. The session is
        closed automatically when the route handler returns.
    """
    async with SessionLocal() as session:
        yield session
