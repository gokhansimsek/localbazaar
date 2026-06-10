"""add product_id FK to every prices_<slug> table and backfill.

Revision ID: 0007_prices_product_id
Revises: 0006_products
Create Date: 2026-06-10

Phase 2 of the products refactor:

- For every enabled city in the ``cities`` registry whose ``prices_<slug>``
  table already exists, add a nullable ``product_id BIGINT REFERENCES
  products(id)`` column.
- Backfill ``product_id`` by reading every distinct
  ``(product_name, product_variety, product_category, unit_name)`` tuple from
  the table, running it through :func:`local_bazaar.products_normalize.normalize`,
  and matching the result against ``products``. Products that the per-city
  scrapers surfaced but that aren't in ``products`` yet (e.g. cultivars only
  Istanbul or Bursa publish) are auto-inserted so every price row ends up
  linked.
- Add an index on ``product_id`` for fast joins from the API.

The migration intentionally leaves the legacy columns
(``product_name``, ``product_variety``, ``product_category``, ``unit_name``)
in place. Phase 3 will drop them once the scrapers and API have been
migrated to write/read ``product_id`` exclusively.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from local_bazaar.products_normalize import normalize

revision: str = "0007_prices_product_id"
down_revision: str | Sequence[str] | None = "0006_products"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn: sa.engine.Connection, table_name: str) -> bool:
    """Return ``True`` if ``table_name`` exists in the current schema.

    Args:
        conn: An active SQLAlchemy connection.
        table_name: Unqualified table name (e.g. ``"prices_istanbul"``).

    Returns:
        ``True`` when ``to_regclass`` resolves the name to an OID.
    """
    return conn.execute(sa.text("SELECT to_regclass(:n)"), {"n": table_name}).scalar() is not None


def _find_or_create_product(
    conn: sa.engine.Connection,
    name: str,
    variety: str | None,
    category: str | None,
    unit: str,
) -> int:
    """Return the ``products.id`` for a normalized tuple, inserting if absent.

    Args:
        conn: An active SQLAlchemy connection.
        name: Canonical product name (already title-cased).
        variety: Canonical variety (or ``None``).
        category: Source category (preserved verbatim).
        unit: Source unit (``Kg`` / ``Adet``).

    Returns:
        The ``products.id`` for the requested tuple.
    """
    pid = conn.execute(
        sa.text(
            """
            SELECT id FROM products
            WHERE name = :name
              AND COALESCE(variety, '') = COALESCE(:variety, '')
              AND COALESCE(category, '') = COALESCE(:category, '')
              AND unit_name = :unit
            LIMIT 1
            """
        ),
        {"name": name, "variety": variety, "category": category, "unit": unit},
    ).scalar()
    if pid is not None:
        return int(pid)
    new_id = conn.execute(
        sa.text(
            """
            INSERT INTO products (name, variety, category, unit_name)
            VALUES (:name, :variety, :category, :unit)
            ON CONFLICT (name, COALESCE(variety, ''), COALESCE(category, ''), unit_name)
            DO UPDATE SET unit_name = EXCLUDED.unit_name
            RETURNING id
            """
        ),
        {"name": name, "variety": variety, "category": category, "unit": unit},
    ).scalar()
    assert new_id is not None
    return int(new_id)


def _backfill_table(conn: sa.engine.Connection, table_name: str) -> tuple[int, int]:
    """Add ``product_id`` to one ``prices_<slug>`` table and backfill it.

    Args:
        conn: An active SQLAlchemy connection.
        table_name: The full table name (``"prices_<slug>"``).

    Returns:
        A ``(distinct_tuples, inserted_products)`` count for diagnostics.
    """
    conn.execute(
        sa.text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS product_id BIGINT")
    )

    distinct_rows = conn.execute(
        sa.text(
            f"""
            SELECT product_name, product_variety, product_category, unit_name
            FROM {table_name}
            GROUP BY product_name, product_variety, product_category, unit_name
            """
        )
    ).all()

    inserted = 0
    seen_before = conn.execute(sa.text("SELECT COUNT(*) FROM products")).scalar_one()
    for raw_name, raw_variety, raw_category, raw_unit in distinct_rows:
        if not raw_name or not raw_unit:
            continue
        clean_name, clean_variety = normalize(raw_name, raw_variety)
        category = (raw_category or "").strip() or None
        unit = raw_unit.strip()

        pid = _find_or_create_product(conn, clean_name, clean_variety, category, unit)

        conn.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET product_id = :pid
                WHERE product_name = :raw_name
                  AND COALESCE(product_variety, '') = COALESCE(:raw_variety, '')
                  AND COALESCE(product_category, '') = COALESCE(:raw_category, '')
                  AND unit_name = :raw_unit
                """
            ),
            {
                "pid": pid,
                "raw_name": raw_name,
                "raw_variety": raw_variety,
                "raw_category": raw_category,
                "raw_unit": raw_unit,
            },
        )

    seen_after = conn.execute(sa.text("SELECT COUNT(*) FROM products")).scalar_one()
    inserted = seen_after - seen_before
    return len(distinct_rows), inserted


def upgrade() -> None:
    """Add and backfill ``product_id`` on every existing ``prices_<slug>`` table."""
    conn = op.get_bind()

    # Drop the old uniqueness rule on products so on-conflict upserts work.
    # The COALESCE-based index from 0006 stays in place.
    cities = conn.execute(
        sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug")
    ).scalars().all()

    for slug in cities:
        table_name = f"prices_{slug}"
        if not _table_exists(conn, table_name):
            continue
        _backfill_table(conn, table_name)
        conn.execute(
            sa.text(
                f"""
                ALTER TABLE {table_name}
                ADD CONSTRAINT fk_{table_name}_product_id
                FOREIGN KEY (product_id) REFERENCES products(id)
                """
            )
        )
        conn.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS ix_{table_name}_product_id "
                f"ON {table_name} (product_id)"
            )
        )


def downgrade() -> None:
    """Drop ``product_id`` from every ``prices_<slug>`` table."""
    conn = op.get_bind()
    cities = conn.execute(
        sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug")
    ).scalars().all()
    for slug in cities:
        table_name = f"prices_{slug}"
        if not _table_exists(conn, table_name):
            continue
        conn.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table_name}_product_id"))
        conn.execute(
            sa.text(f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS fk_{table_name}_product_id")
        )
        conn.execute(sa.text(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS product_id"))
