"""create users and place_suggestions tables.

Revision ID: 0014_user_place_suggestions
Revises: 0013_merge_turp_otu
Create Date: 2026-06-29

Adds lightweight (password-less) users and their place suggestion requests:

- ``users`` — first/last name, a unique email (the dedup key), and optional
  city/town (province/district) FKs.
- ``place_suggestions`` — one ``add`` or ``update`` request per row, stored
  ``pending`` for manual review. ``add`` rows carry the proposed name/type and
  pinned coordinates; ``update`` rows reference an existing ``markets`` row.

Column types mirror the SQLModel definitions in ``models.py`` so a fresh
``SQLModel.metadata.create_all`` (used by the test fixture) and a migrated
database agree.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_user_place_suggestions"
down_revision: str | Sequence[str] | None = "0013_merge_turp_otu"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``users`` and ``place_suggestions`` tables."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column("last_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("province_id", sa.Integer(), nullable=True),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["province_id"], ["provinces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["district_id"], ["districts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique index doubles as the ON CONFLICT (email) target for the upsert.
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_province_id", "users", ["province_id"])
    op.create_index("ix_users_district_id", "users", ["district_id"])

    op.create_table(
        "place_suggestions",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("suggestion_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("proposed_name", sa.String(length=255), nullable=True),
        sa.Column("proposed_market_type", sa.String(length=32), nullable=True),
        sa.Column("province_id", sa.Integer(), nullable=True),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["province_id"], ["provinces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["district_id"], ["districts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_place_suggestions_user_id", "place_suggestions", ["user_id"])
    op.create_index("ix_place_suggestions_status", "place_suggestions", ["status"])
    op.create_index("ix_place_suggestions_market_id", "place_suggestions", ["market_id"])


def downgrade() -> None:
    """Drop the ``place_suggestions`` and ``users`` tables."""
    op.drop_index("ix_place_suggestions_market_id", table_name="place_suggestions")
    op.drop_index("ix_place_suggestions_status", table_name="place_suggestions")
    op.drop_index("ix_place_suggestions_user_id", table_name="place_suggestions")
    op.drop_table("place_suggestions")
    op.drop_index("ix_users_district_id", table_name="users")
    op.drop_index("ix_users_province_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
