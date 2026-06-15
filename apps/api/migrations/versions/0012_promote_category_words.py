"""promote category-like words out of products.variety.

Revision ID: 0012_promote_category_words
Revises: 0011_normalize_categories
Create Date: 2026-06-10

Per-city sources sometimes write trade / origin tags (``İthal``, ``Yerli``)
into the ``variety`` column when they belong in ``category``. This migration
applies :func:`local_bazaar.products_normalize.promote_category_words` to
every existing row and merges the resulting collisions on the
``(name, variety, category, unit_name)`` unique index. Going forward the
scraper UPSERT path runs the same helper after :func:`normalize`, so new
rows are clean from creation.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from local_bazaar.products_normalize import promote_category_words

revision: str = "0012_promote_category_words"
down_revision: str | Sequence[str] | None = "0011_normalize_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn: sa.engine.Connection, table_name: str) -> bool:
    """Return ``True`` if ``table_name`` exists in the current schema."""
    return conn.execute(sa.text("SELECT to_regclass(:n)"), {"n": table_name}).scalar() is not None


def _remap_product(
    conn: sa.engine.Connection,
    cities: list[str],
    from_id: int,
    to_id: int,
) -> None:
    """Move every ``prices_<slug>`` row from one ``product_id`` to another."""
    if from_id == to_id:
        return
    for slug in cities:
        table = f"prices_{slug}"
        if not _table_exists(conn, table):
            continue
        conn.execute(
            sa.text(
                f"""
                DELETE FROM {table} src
                USING {table} dst
                WHERE src.product_id = :from_id
                  AND dst.product_id = :to_id
                  AND dst.bulletin_date = src.bulletin_date
                """
            ),
            {"from_id": from_id, "to_id": to_id},
        )
        conn.execute(
            sa.text(f"UPDATE {table} SET product_id = :to_id WHERE product_id = :from_id"),
            {"from_id": from_id, "to_id": to_id},
        )


def upgrade() -> None:
    """Promote stray category words and merge resulting duplicates."""
    conn = op.get_bind()
    cities: list[str] = list(
        conn.execute(
            sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug")
        ).scalars().all()
    )

    rows = conn.execute(
        sa.text("SELECT id, name, variety, category, unit_name FROM products")
    ).all()

    resolved: list[tuple[int, str, str, str, str]] = []
    for pid, name, variety, category, unit in rows:
        new_name, new_variety, new_category = promote_category_words(name, variety, category)
        resolved.append(
            (pid, new_name, new_variety or "", new_category, unit)
        )

    resolved.sort(key=lambda r: r[0])
    canonical: dict[tuple[str, str, str, str], int] = {}
    for pid, name, variety, category, unit in resolved:
        key = (name, variety, category, unit)
        canonical.setdefault(key, pid)

    # Pass 1: remap + delete non-canonicals so the unique index frees up.
    for pid, name, variety, category, unit in resolved:
        key = (name, variety, category, unit)
        keeper = canonical[key]
        if pid != keeper:
            _remap_product(conn, cities, pid, keeper)
            conn.execute(sa.text("DELETE FROM products WHERE id = :pid"), {"pid": pid})

    # Pass 2: rewrite the canonical row to the new (variety, category) pair.
    # NULL ↔ empty-string mismatch: bind variety as ``None`` when empty so
    # the column actually goes back to NULL.
    for pid, name, variety, category, unit in resolved:
        key = (name, variety, category, unit)
        if canonical[key] != pid:
            continue
        conn.execute(
            sa.text("UPDATE products SET variety = :v, category = :c WHERE id = :pid"),
            {"pid": pid, "v": variety or None, "c": category},
        )


def downgrade() -> None:
    """No reversal — the source variety/category split is lossy."""
