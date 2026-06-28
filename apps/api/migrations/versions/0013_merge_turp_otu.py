"""merge split ``Turp`` / ``Otu`` products into the compound ``Turp Otu``.

Revision ID: 0013_merge_turp_otu
Revises: 0012_promote_category_words
Create Date: 2026-06-28

``Turp Otu`` (radish greens) is a single product, but it was missing from
:data:`local_bazaar.products_normalize._COMPOUND_NAMES`. As a result, whenever
a source duplicated the name into the variety column
(``product_name="Turp Otu"`` / ``product_variety="Turp Otu"``), the normalizer
split it into ``name="Turp"`` + ``variety="Otu"`` — the same fate the other
``… Otu`` herbs (``Hardal Otu``, ``Limon Otu``, ``Mizuna Otu``) were protected
from. ``Turp Otu`` is now in the compound set, so new rows resolve correctly.

This migration fixes the rows already seeded with the split form: it rewrites
``(Turp, Otu)`` products to ``(Turp Otu, NULL)`` and merges any collision with
a pre-existing ``Turp Otu`` row on the ``(name, variety, category, unit_name)``
unique index, re-pointing every per-city ``prices_<slug>.product_id`` FK first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_merge_turp_otu"
down_revision: str | Sequence[str] | None = "0012_promote_category_words"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Stored (name, variety) pairs to fold into a canonical (name, variety).
# Keys/values are the exact title-cased forms stored in ``products``.
_MERGES: dict[tuple[str, str | None], tuple[str, str | None]] = {
    ("Turp", "Otu"): ("Turp Otu", None),
}


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
    """Fold split ``(Turp, Otu)`` products into the canonical ``Turp Otu``."""
    conn = op.get_bind()
    cities: list[str] = list(
        conn.execute(sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug"))
        .scalars()
        .all()
    )

    rows = conn.execute(
        sa.text("SELECT id, name, variety, category, unit_name FROM products")
    ).all()

    # Apply the merge map to every row; rows not in the map pass through.
    resolved: list[tuple[int, str, str, str, str]] = []
    for pid, name, variety, category, unit in rows:
        new_name, new_variety = _MERGES.get((name, variety), (name, variety))
        resolved.append((pid, new_name, new_variety or "", category, unit))

    # Lowest id wins as the canonical keeper for each target identity.
    resolved.sort(key=lambda r: r[0])
    canonical: dict[tuple[str, str, str, str], int] = {}
    for pid, name, variety, category, unit in resolved:
        canonical.setdefault((name, variety, category, unit), pid)

    # Pass 1: remap FKs off non-canonical rows, then delete them so the unique
    # index frees up before the canonical rewrite.
    for pid, name, variety, category, unit in resolved:
        keeper = canonical[(name, variety, category, unit)]
        if pid != keeper:
            _remap_product(conn, cities, pid, keeper)
            conn.execute(sa.text("DELETE FROM products WHERE id = :pid"), {"pid": pid})

    # Pass 2: rewrite the surviving canonical rows to the merged (name, variety).
    # Empty variety binds back to NULL (the column is nullable).
    for pid, name, variety, category, unit in resolved:
        if canonical[(name, variety, category, unit)] != pid:
            continue
        conn.execute(
            sa.text("UPDATE products SET name = :n, variety = :v WHERE id = :pid"),
            {"pid": pid, "n": name, "v": variety or None},
        )


def downgrade() -> None:
    """No reversal — the original (Turp, Otu) split is lossy."""
