"""delete fish/seafood rows from every prices_<slug> table.

Revision ID: 0008_drop_non_produce
Revises: 0007_prices_product_id
Create Date: 2026-06-10

Project scope is fruit + vegetable wholesale prices, including imported
produce. Earlier scraper revisions fetched fish/seafood (hal.gov.tr ulusal
table; Ankara ``fish`` type; Bursa ``Su Ürünleri`` / ``Pelajik`` / ``Dip``
tabs). The corresponding source-level paths have been removed in the same
change set; this migration cleans the rows they already left behind.

Imported produce (``İthal``) is in scope and is NOT deleted.

The cleanup happens in two passes:

1. **By product name** — :func:`local_bazaar.products_normalize.is_fish_name`
   identifies fish/seafood entries regardless of which table they sit in.
2. **By stored category** — for tables that carry a ``product_category``
   value (Ankara, Bursa), additionally drop rows whose category mentions
   fish/seafood (``Balık`` / ``Su Ürünleri`` / ``Pelajik`` / ``Dip`` / etc.).

Finally, prune any ``products`` row that no longer has a price reference, so
the taxonomy stays in sync with what we actually publish.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from local_bazaar.products_normalize import is_fish_name

revision: str = "0008_drop_non_produce"
down_revision: str | Sequence[str] | None = "0007_prices_product_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Category values that mean "fish/seafood" — case-insensitive matched.
# ``İthal`` (imported produce) is intentionally NOT in this list.
_NON_PRODUCE_CATEGORY_HINTS: tuple[str, ...] = (
    "balık",
    "balik",
    "su ürünleri",
    "su urunleri",
    "pelajik",
    "dip",
    "iç su",
    "i̇ç su",
    "diğer su",
    "kültür balık",
    "kültür balıkları",
)


def _table_exists(conn: sa.engine.Connection, table_name: str) -> bool:
    """Return ``True`` if ``table_name`` exists in the current schema."""
    return conn.execute(sa.text("SELECT to_regclass(:n)"), {"n": table_name}).scalar() is not None


def upgrade() -> None:
    """Delete fish/seafood/imported rows from every prices_<slug> table."""
    conn = op.get_bind()
    cities = conn.execute(
        sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug")
    ).scalars().all()

    for slug in cities:
        table_name = f"prices_{slug}"
        if not _table_exists(conn, table_name):
            continue

        # Pass 1 — find every fish/seafood product name in this table and
        # delete its rows. We pull the distinct product_name list into Python
        # so :func:`is_fish_name` can use the same logic the scrapers do.
        distinct_names = conn.execute(
            sa.text(f"SELECT DISTINCT product_name FROM {table_name}")
        ).scalars().all()
        fish_names = [n for n in distinct_names if is_fish_name(n)]
        if fish_names:
            conn.execute(
                sa.text(f"DELETE FROM {table_name} WHERE product_name = ANY(:names)"),
                {"names": fish_names},
            )

        # Pass 2 — for tables with a meaningful product_category (Ankara,
        # Bursa), drop rows whose category isn't Meyve or Sebze.
        for hint in _NON_PRODUCE_CATEGORY_HINTS:
            conn.execute(
                sa.text(
                    f"DELETE FROM {table_name} "
                    f"WHERE LOWER(product_category) = LOWER(:hint)"
                ),
                {"hint": hint},
            )

    # Pass 3 — prune orphaned products that no city references anymore.
    union_sql = "\nUNION\n".join(
        f"SELECT product_id FROM prices_{slug} WHERE product_id IS NOT NULL"
        for slug in cities
        if _table_exists(conn, f"prices_{slug}")
    )
    if union_sql:
        conn.execute(
            sa.text(
                f"""
                DELETE FROM products
                WHERE id NOT IN ({union_sql})
                """
            )
        )


def downgrade() -> None:
    """Cleanup migration — no automatic restore. Re-run the scrapers if needed."""
    # Re-introducing the deleted rows isn't feasible without re-scraping the
    # sources. Downgrade is a no-op; a clean reset is to drop the per-city
    # tables and let the daily job rebuild them with the new scraper scope.
