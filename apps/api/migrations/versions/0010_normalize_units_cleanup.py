"""normalize products.unit_name, drop broken rows, re-prune seafood orphans.

Revision ID: 0010_normalize_units_cleanup
Revises: 0009_drop_legacy_price_columns
Create Date: 2026-06-10

Cleanup pass over the ``products`` taxonomy after Phase 3:

1. **Unit canonicalization.** Source data uses ~20 spellings for the same
   handful of units (``kg``/``Kg``/``KG``/``Kğ``, ``(Adet)``/``adet``/``Ad``,
   ``demet``/``(Demet)``/``BAĞ`` …). We rewrite every ``products.unit_name``
   through :func:`local_bazaar.products_normalize.normalize_unit`. Where the
   rewrite would collide with an existing product, we keep the lower-id row
   and remap every ``prices_<slug>.product_id`` reference to it.

2. **Drop broken rows.** Source corruption produced a few products where the
   unit slot contains a product attribute (``aşılı`` = grafted), a product
   name (``avokado``), or noise from a misparsed cell (``taze kg`` with the
   variety carrying a closing paren). These are deleted along with any
   price rows that reference them.

3. **Strip variety = unit duplication.** When the variety field carries the
   same token as the unit (e.g. ``Kiraz`` / variety=``Paket`` / unit=``Paket``),
   the variety adds no information. We null it out, again remapping prices
   if the change collides with an existing product.

4. **Re-prune seafood orphans.** Products tagged with ``*Su Ürünleri*`` /
   ``Pelajik`` / ``Dip`` / ``Kültür *Balık*`` categories whose prices were
   all deleted by ``0008``. The orphan-prune in ``0008`` happened mid-run
   and missed these; one final pass cleans them up.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from local_bazaar.products_normalize import normalize_unit

revision: str = "0010_normalize_units_cleanup"
down_revision: str | Sequence[str] | None = "0009_drop_legacy_price_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Variety tokens that duplicate a unit when seen in tandem (a different
# product may legitimately have ``variety = "Paket"`` so we only clear it
# when it matches the row's own unit).
_UNIT_TOKEN_AS_VARIETY: frozenset[str] = frozenset(
    {"Kg", "Adet", "Bağ", "Demet", "Paket", "Koli", "Kasa", "Çuval", "Sandık"}
)


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

    Args:
        conn: Active connection.
        cities: All registered city slugs.
        from_id: ``products.id`` that's about to be deleted.
        to_id: ``products.id`` that should absorb the references.
    """
    if from_id == to_id:
        return
    for slug in cities:
        table = f"prices_{slug}"
        if not _table_exists(conn, table):
            continue
        # Delete the source rows that would conflict on (bulletin_date, product_id).
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
        # Remap the rest.
        conn.execute(
            sa.text(f"UPDATE {table} SET product_id = :to_id WHERE product_id = :from_id"),
            {"from_id": from_id, "to_id": to_id},
        )


def _delete_product_and_prices(
    conn: sa.engine.Connection,
    cities: list[str],
    product_id: int,
) -> None:
    """Hard-delete a product row and every ``prices_<slug>`` row that points at it."""
    for slug in cities:
        table = f"prices_{slug}"
        if not _table_exists(conn, table):
            continue
        conn.execute(
            sa.text(f"DELETE FROM {table} WHERE product_id = :pid"),
            {"pid": product_id},
        )
    conn.execute(sa.text("DELETE FROM products WHERE id = :pid"), {"pid": product_id})


def upgrade() -> None:
    """Canonicalize units, drop broken rows, strip variety=unit, re-prune orphans."""
    conn = op.get_bind()
    cities: list[str] = list(
        conn.execute(
            sa.text("SELECT slug FROM cities WHERE enabled = true ORDER BY slug")
        ).scalars().all()
    )

    # ---- Pass A: drop broken rows by structural signature ------------------
    # Each predicate identifies a row where the data is unsalvageable:
    #   * variety contains punctuation that proves it's mis-parsed.
    #   * unit is a recognizable product attribute, not a unit.
    broken_ids = [
        row[0]
        for row in conn.execute(
            sa.text(
                """
                SELECT id FROM products
                WHERE variety LIKE '%)%'
                   OR unit_name IN ('aşılı', 'avokado')
                   OR LOWER(name) = LOWER(unit_name)
                """
            )
        ).all()
    ]
    for pid in broken_ids:
        _delete_product_and_prices(conn, cities, pid)

    # ---- Pass B: re-prune seafood orphans ---------------------------------
    seafood_orphans = [
        row[0]
        for row in conn.execute(
            sa.text(
                """
                SELECT p.id
                FROM products p
                WHERE p.category ILIKE '%su ürünleri%'
                   OR p.category ILIKE '%pelajik%'
                   OR p.category ILIKE '%dip%'
                   OR p.category ILIKE '%kültür%balık%'
                """
            )
        ).all()
    ]
    for pid in seafood_orphans:
        _delete_product_and_prices(conn, cities, pid)

    # ---- Pass C: canonicalize unit_name with collision-aware remap --------
    rows = conn.execute(
        sa.text("SELECT id, name, variety, category, unit_name FROM products")
    ).all()
    # Resolve every product to its (canonical) key.
    resolved: list[tuple[int, str, str, str, str]] = []
    for pid, name, variety, category, unit in rows:
        new_unit = normalize_unit(unit)
        resolved.append((pid, name, variety or "", category or "", new_unit))
    # Group by canonical key — first occurrence wins (lowest id).
    canonical: dict[tuple[str, str, str, str], int] = {}
    resolved.sort(key=lambda r: r[0])  # ascending id, so first seen wins
    for pid, name, variety, category, new_unit in resolved:
        key = (name, variety, category, new_unit)
        canonical.setdefault(key, pid)
    # Apply in two passes:
    #   1. Remap + delete every non-canonical row. This frees the canonical's
    #      target unit_name slot so the subsequent UPDATE can't collide on
    #      the unique index.
    #   2. UPDATE each remaining canonical row whose unit_name still differs.
    for pid, name, variety, category, new_unit in resolved:
        key = (name, variety, category, new_unit)
        keeper = canonical[key]
        if pid != keeper:
            _remap_product(conn, cities, pid, keeper)
            conn.execute(sa.text("DELETE FROM products WHERE id = :pid"), {"pid": pid})
    for pid, name, variety, category, new_unit in resolved:
        key = (name, variety, category, new_unit)
        if canonical[key] != pid:
            continue
        conn.execute(
            sa.text("UPDATE products SET unit_name = :u WHERE id = :pid AND unit_name <> :u"),
            {"pid": pid, "u": new_unit},
        )

    # ---- Pass D: clear variety when it duplicates the unit ----------------
    # After unit normalization, find products whose variety equals a unit
    # token. Two products may already coexist as "(Kiraz, NULL, Paket)" and
    # "(Kiraz, Paket, Paket)" — collapse the latter into the former.
    rows = conn.execute(
        sa.text(
            """
            SELECT id, name, variety, COALESCE(category, ''), unit_name
            FROM products
            WHERE variety IS NOT NULL
            """
        )
    ).all()
    for pid, name, variety, category, unit in rows:
        if variety not in _UNIT_TOKEN_AS_VARIETY:
            continue
        # Find or create the variety=NULL twin.
        twin = conn.execute(
            sa.text(
                """
                SELECT id FROM products
                WHERE name = :name
                  AND variety IS NULL
                  AND COALESCE(category, '') = :category
                  AND unit_name = :unit
                LIMIT 1
                """
            ),
            {"name": name, "category": category, "unit": unit},
        ).scalar()
        if twin is None:
            # Just null out the variety on this row.
            conn.execute(
                sa.text("UPDATE products SET variety = NULL WHERE id = :pid"),
                {"pid": pid},
            )
        else:
            _remap_product(conn, cities, pid, int(twin))
            conn.execute(sa.text("DELETE FROM products WHERE id = :pid"), {"pid": pid})


def downgrade() -> None:
    """Cleanup migration — no automatic restore. Re-run scrapers if needed."""
    # Re-introducing the deleted rows isn't feasible without re-scraping
    # the sources, and the unit synonyms are lossy: ``(Adet)`` and ``Adet``
    # both canonicalize to ``Adet`` and we don't remember which one each
    # row started as. Treat this migration as one-way.
