"""create newsletter_subscribers table.

Revision ID: 0015_newsletter_subscribers
Revises: 0014_user_place_suggestions
Create Date: 2026-09-15

Stores signups from the site footer's newsletter form: one row per opted-in
email. The unique email index is the ``ON CONFLICT`` target, so a repeat
signup is a no-op. ``created_at`` doubles as the consent timestamp (the form
requires an explicit consent checkbox).

Column types mirror ``NewsletterSubscriber`` in ``models.py`` so a fresh
``SQLModel.metadata.create_all`` (used by the test fixture) and a migrated
database agree.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_newsletter_subscribers"
down_revision: str | Sequence[str] | None = "0014_user_place_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``newsletter_subscribers`` table."""
    op.create_table(
        "newsletter_subscribers",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_newsletter_subscribers_email", "newsletter_subscribers", ["email"], unique=True
    )


def downgrade() -> None:
    """Drop the ``newsletter_subscribers`` table."""
    op.drop_index("ix_newsletter_subscribers_email", table_name="newsletter_subscribers")
    op.drop_table("newsletter_subscribers")
