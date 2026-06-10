"""create products table and seed it from prices_national.

Revision ID: 0006_products
Revises: 0005_page_views
Create Date: 2026-06-10

Phase 1 of the products refactor:

- Create a normalized ``products`` registry: ``(id, name, variety, category,
  unit_name)`` with a uniqueness rule treating NULL variety/category as empty
  for dedup purposes.
- Populate it from the distinct ``(product_name, product_variety,
  product_category, unit_name)`` tuples in ``prices_national``, applying the
  normalization rules implemented in :mod:`local_bazaar.products_normalize`.

The migration does NOT alter per-city ``prices_*`` tables — that's
``0007_prices_product_id`` (Phase 2).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from local_bazaar.products_normalize import normalize

revision: str = "0006_products"
down_revision: str | Sequence[str] | None = "0005_page_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``products`` and populate it from ``prices_national``."""
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("variety", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("unit_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_name", "products", ["name"])
    # PostgreSQL UNIQUE treats NULL as distinct from NULL, so two rows that
    # differ only by NULL variety would both pass. COALESCE in a unique
    # expression index forces dedup the way we mean it.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_products_full ON products (
                name,
                COALESCE(variety, ''),
                COALESCE(category, ''),
                unit_name
            )
            """
        )
    )

    conn = op.get_bind()
    distinct_rows = conn.execute(
        sa.text(
            """
            SELECT product_name, product_variety, product_category, unit_name
            FROM prices_national
            GROUP BY product_name, product_variety, product_category, unit_name
            """
        )
    ).all()

    seen: set[tuple[str, str, str, str]] = set()
    for row in distinct_rows:
        src_name, src_variety, src_category, src_unit = row
        if not src_name or not src_unit:
            continue
        name, variety = normalize(src_name, src_variety)
        category = (src_category or "").strip() or None
        unit = src_unit.strip()

        # Dedup using the same COALESCE-style key the unique index enforces.
        key = (name, variety or "", category or "", unit)
        if key in seen:
            continue
        seen.add(key)
        conn.execute(
            sa.text(
                """
                INSERT INTO products (name, variety, category, unit_name)
                VALUES (:name, :variety, :category, :unit)
                ON CONFLICT DO NOTHING
                """
            ),
            {"name": name, "variety": variety, "category": category, "unit": unit},
        )


def downgrade() -> None:
    """Drop the products table."""
    op.drop_index("uq_products_full", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_table("products")
