"""drop legacy product_* / unit_name columns from every prices_<slug>.

Revision ID: 0009_drop_legacy_price_columns
Revises: 0008_drop_non_produce
Create Date: 2026-06-10

Phase 3 of the products refactor:

- Switch each ``prices_<slug>`` uniqueness rule from
  ``(bulletin_date, product_name, product_variety, product_category, unit_name)``
  to ``(bulletin_date, product_id)``.
- Drop the four legacy text columns plus the now-redundant
  ``ix_<table>_product_name`` index.
- Mark ``product_id`` as ``NOT NULL`` (every row was already linked in 0007
  and the manual backfill that followed).

After this migration, the API joins ``prices_<slug>`` with ``products`` to
reconstruct the human-readable product fields on its way out the door. The
scraper UPSERT path was updated in the same change set to write only
``(bulletin_date, product_id, average_price, transaction_volume)``.

The migration aborts if any row in any per-city table still has a NULL
``product_id``. That should be impossible after 0007 + the post-fish
re-scrape + the Antalya rescrape, but the safety check protects against
running this on a database where some scrape failed mid-flight.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_drop_legacy_price_columns"
down_revision: str | Sequence[str] | None = "0008_drop_non_produce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn: sa.engine.Connection, table_name: str) -> bool:
    """Return ``True`` if ``table_name`` exists in the current schema."""
    return conn.execute(sa.text("SELECT to_regclass(:n)"), {"n": table_name}).scalar() is not None


def upgrade() -> None:
    """Drop legacy columns and swap the uniqueness rule on every prices table."""
    conn = op.get_bind()
    cities = (
        conn.execute(sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug"))
        .scalars()
        .all()
    )

    # Phase A — safety check: every existing row must have product_id set.
    for slug in cities:
        table_name = f"prices_{slug}"
        if not _table_exists(conn, table_name):
            continue
        unlinked = conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE product_id IS NULL")
        ).scalar_one()
        if unlinked:
            raise RuntimeError(
                f"{table_name} still has {unlinked} rows with NULL product_id; "
                "run the Phase 2 backfill before applying this migration."
            )

    # Phase B — swap uniqueness, drop legacy columns + index.
    for slug in cities:
        table_name = f"prices_{slug}"
        if not _table_exists(conn, table_name):
            continue
        # Force NOT NULL on product_id now that we've verified it.
        conn.execute(sa.text(f"ALTER TABLE {table_name} ALTER COLUMN product_id SET NOT NULL"))
        # Dedup: the old uniqueness allowed two rows with different raw tuples
        # that nonetheless map to the same product_id after normalization
        # (e.g. "DOMATES SALKIM" vs "DOMATES SALKIM (DİĞER)" both → product 704).
        # Keep the most recently updated row per (bulletin_date, product_id).
        conn.execute(
            sa.text(
                f"""
                DELETE FROM {table_name}
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY bulletin_date, product_id
                            ORDER BY last_updated DESC, id DESC
                        ) AS rn
                        FROM {table_name}
                    ) t
                    WHERE rn > 1
                )
                """
            )
        )
        # Drop the legacy uniqueness rule and replace with (bulletin_date, product_id).
        conn.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"DROP CONSTRAINT IF EXISTS uq_{table_name}_bulletin_product"
            )
        )
        conn.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"ADD CONSTRAINT uq_{table_name}_bulletin_product_id "
                f"UNIQUE (bulletin_date, product_id)"
            )
        )
        # Drop the index that was scoped to product_name. The new
        # ix_<table>_product_id is sufficient.
        conn.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table_name}_product_name"))
        # Drop the four legacy columns.
        for col in ("product_name", "product_variety", "product_category", "unit_name"):
            conn.execute(sa.text(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {col}"))


def downgrade() -> None:
    """Re-add legacy columns. Data is NOT restored — re-scrape if you need it."""
    conn = op.get_bind()
    cities = (
        conn.execute(sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug"))
        .scalars()
        .all()
    )
    for slug in cities:
        table_name = f"prices_{slug}"
        if not _table_exists(conn, table_name):
            continue
        conn.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN IF NOT EXISTS product_name TEXT, "
                f"ADD COLUMN IF NOT EXISTS product_variety TEXT, "
                f"ADD COLUMN IF NOT EXISTS product_category TEXT, "
                f"ADD COLUMN IF NOT EXISTS unit_name TEXT"
            )
        )
        # Backfill the text columns from products so the data is at least
        # readable, but leave any new NOT NULL constraints off — re-scraping
        # is the right way to fully restore.
        conn.execute(
            sa.text(
                f"""
                UPDATE {table_name} t
                SET product_name = p.name,
                    product_variety = p.variety,
                    product_category = p.category,
                    unit_name = p.unit_name
                FROM products p
                WHERE p.id = t.product_id
                """
            )
        )
        conn.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"DROP CONSTRAINT IF EXISTS uq_{table_name}_bulletin_product_id"
            )
        )
        conn.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"ADD CONSTRAINT uq_{table_name}_bulletin_product "
                f"UNIQUE (bulletin_date, product_name, product_variety, product_category, unit_name)"
            )
        )
        conn.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS ix_{table_name}_product_name "
                f"ON {table_name} (product_name)"
            )
        )
        conn.execute(sa.text(f"ALTER TABLE {table_name} ALTER COLUMN product_id DROP NOT NULL"))
