"""normalize products.category to the four canonical hal-grade values.

Revision ID: 0011_normalize_categories
Revises: 0010_normalize_units_cleanup
Create Date: 2026-06-10

The ``products.category`` column is intended to carry one of the four
quality / origin grades published by Turkish wholesale sources:

* ``Geleneksel(Konvansiyonel)``
* ``İyi Tarım``
* ``Organik Tarım``
* ``İthal``

Per-city scrapers have historically written category-like strings into the
slot — ``Meyve`` and ``Sebze`` (Bursa tab labels), or simply ``NULL`` —
which produces apparent duplicates (e.g. a ``"Ananas"`` row under ``İthal``
and another under ``NULL``).

This migration:

1. Rewrites every non-canonical ``category`` value (including ``NULL``,
   ``Meyve``, ``Sebze`` and any future stray) to
   ``Geleneksel(Konvansiyonel)``.
2. Merges any product collisions that result on the
   ``(name, COALESCE(variety,''), COALESCE(category,''), unit_name)``
   unique index, remapping ``prices_<slug>.product_id`` references to the
   keeper row before deleting the duplicate.

Going forward the scraper UPSERT path (``base._resolve_product_id``) calls
:func:`local_bazaar.products_normalize.normalize_category`, so new rows are
canonical from creation.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from local_bazaar.products_normalize import normalize_category

revision: str = "0011_normalize_categories"
down_revision: str | Sequence[str] | None = "0010_normalize_units_cleanup"
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
    """Move every ``prices_<slug>`` row from one ``product_id`` to another.

    Drops any source-id row that would violate ``(bulletin_date, product_id)``
    uniqueness against the destination (keeping the destination row).
    """
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
    """Canonicalize categories and merge resulting duplicates."""
    conn = op.get_bind()
    cities: list[str] = list(
        conn.execute(
            sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug")
        ).scalars().all()
    )

    rows = conn.execute(
        sa.text("SELECT id, name, variety, category, unit_name FROM products")
    ).all()

    # Resolve every product to its (canonical) key.
    resolved: list[tuple[int, str, str, str, str]] = []
    for pid, name, variety, category, unit in rows:
        new_category = normalize_category(category)
        resolved.append((pid, name, variety or "", new_category, unit))
    # Group by canonical key — lowest id wins.
    resolved.sort(key=lambda r: r[0])
    canonical: dict[tuple[str, str, str, str], int] = {}
    for pid, name, variety, new_category, unit in resolved:
        key = (name, variety, new_category, unit)
        canonical.setdefault(key, pid)

    # Two passes (same pattern as 0010):
    #   1. Remap + delete non-canonicals so the unique index slot frees up.
    #   2. UPDATE category on each remaining canonical row whose value differs.
    for pid, name, variety, new_category, unit in resolved:
        key = (name, variety, new_category, unit)
        keeper = canonical[key]
        if pid != keeper:
            _remap_product(conn, cities, pid, keeper)
            conn.execute(sa.text("DELETE FROM products WHERE id = :pid"), {"pid": pid})
    for pid, name, variety, new_category, unit in resolved:
        key = (name, variety, new_category, unit)
        if canonical[key] != pid:
            continue
        conn.execute(
            sa.text(
                "UPDATE products SET category = :c "
                "WHERE id = :pid AND COALESCE(category, '') <> :c"
            ),
            {"pid": pid, "c": new_category},
        )


def downgrade() -> None:
    """No reversal — the source classification is lost."""
    # We can't tell post-migration whether a row's original category was
    # ``NULL``, ``Meyve``, ``Sebze``, etc. — all collapsed to
    # ``Geleneksel(Konvansiyonel)``. Re-scraping is the right way to
    # reconstruct any specific historical state.
