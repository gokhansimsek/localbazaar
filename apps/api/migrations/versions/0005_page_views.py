"""create page_views counter table.

Revision ID: 0005_page_views
Revises: 0004_seed_city_scrapers
Create Date: 2026-06-10

A single row per public-facing UI path (``/``, ``/prices``, ``/trends``,
``/markets``, ``/products/[name]``, ...) with a counter that is atomically
incremented every time the frontend pings ``POST /api/page-views``. Dynamic
routes are bucketed by the frontend before submission, so the table grows by
"public routes that exist", not by "products visited".

The unique index on ``path`` enables ``INSERT ... ON CONFLICT DO UPDATE`` for
race-free increments.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_page_views"
down_revision: str | Sequence[str] | None = "0004_seed_city_scrapers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``page_views`` plus its unique index on ``path``."""
    op.create_table(
        "page_views",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("path", sa.String(length=256), nullable=False),
        sa.Column("visit_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "first_visited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_visited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_page_views_path"),
    )


def downgrade() -> None:
    """Drop the ``page_views`` table."""
    op.drop_table("page_views")
