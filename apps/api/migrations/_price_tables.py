"""Shared helper for migrations that must touch every ``prices_<slug>`` table.

Earlier migrations (0007, 0008, 0009, 0010, 0011, 0012, 0013) discover which
``prices_<slug>`` tables to touch by reading ``SELECT slug FROM cities WHERE
enabled = true``. That silently skips a city's table if the city is ever
disabled while its table still holds data, which violates the "per-city
tables are sacred" invariant in ``CLAUDE.md`` (a schema change must apply to
*every* ``prices_*`` table, not just the ones for currently-enabled cities).

Those already-applied migrations are left untouched — rewriting a migration
after it has run in production risks a fresh environment (a new dev machine,
a test database, disaster recovery) diverging from what production actually
has. Instead, use :func:`existing_price_table_names` in the *next* migration
that needs to iterate every ``prices_*`` table, so the bug is not repeated.
"""

from __future__ import annotations

import sqlalchemy as sa


def existing_price_table_names(conn: sa.engine.Connection) -> list[str]:
    """Return every ``prices_<slug>`` table that actually exists.

    Discovers tables directly from the catalog instead of joining through
    the ``cities`` registry, so a disabled city's table is still covered by
    schema-wide migrations.

    Args:
        conn: An active SQLAlchemy connection.

    Returns:
        Table names (e.g. ``["prices_ankara", "prices_national", ...]``),
        sorted for deterministic migration output.
    """
    rows = conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'prices\\_%' ESCAPE '\\' "
            "ORDER BY table_name"
        )
    ).scalars()
    return list(rows)
