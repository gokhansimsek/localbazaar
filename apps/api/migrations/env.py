"""Alembic environment.

Reads the DB URL from local_bazaar.config, registers the static (registry) tables for
autogenerate, and exposes a sync wrapper around the async engine for offline-mode runs.
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from local_bazaar import models
from local_bazaar.config import settings

# Side-effect import: referencing `models` here registers every SQLModel class
# with SQLModel.metadata so Alembic autogenerate can see them.
_ = models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def _run_online() -> None:
    """Run online migrations on an event loop psycopg can use.

    On Windows the default ``ProactorEventLoop`` is incompatible with
    psycopg's async mode, so we run on a ``SelectorEventLoop`` there. Other
    platforms use the default loop.
    """
    if sys.platform == "win32":
        asyncio.run(
            run_migrations_online(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    _run_online()
