"""widen markets.address from VARCHAR(512) to TEXT.

Revision ID: 0003_widen_markets_address
Revises: 0002_seed_tr_geography
Create Date: 2026-05-13

Some real hal.gov.tr bazaar-location addresses run well over 512 characters
(e.g. an İstanbul / Fatih market that lists every bordering street as part of
its address). VARCHAR(512) truncates those at the database layer, breaking
the bazaar_locations scraper with a StringDataRightTruncation. Postgres has
no performance penalty for TEXT over VARCHAR, so widen the column outright
rather than play whack-a-mole with limits.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_widen_markets_address"
down_revision: str | Sequence[str] | None = "0002_seed_tr_geography"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen ``markets.address`` to ``TEXT``."""
    op.alter_column(
        "markets",
        "address",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Narrow ``markets.address`` back to ``VARCHAR(512)``.

    Truncates existing values that overflow the narrower type; downgrading is
    therefore lossy. Avoid running this on a populated DB unless you have a
    backup.
    """
    op.execute(
        sa.text("UPDATE markets SET address = LEFT(address, 512) WHERE LENGTH(address) > 512")
    )
    op.alter_column(
        "markets",
        "address",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
