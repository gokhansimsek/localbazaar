"""initial schema: registry + national prices + geography + markets

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-13

Single consolidated baseline that previously lived across three files
(0001_initial_registry, 0002_markets_and_geography, 0003_markets_relax_unique).
This is the end-state schema and is intended to run against an empty database
(e.g. a fresh RDS instance).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the consolidated baseline schema."""
    # --- cities -----------------------------------------------------------
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="hal_gov_tr"),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_cities_slug"),
    )
    op.create_index("ix_cities_slug", "cities", ["slug"], unique=True)

    # --- scrape_runs ------------------------------------------------------
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("scraper", sa.String(length=64), nullable=False),
        sa.Column("city_slug", sa.String(length=64), nullable=True),
        sa.Column("bulletin_date", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_runs_scraper", "scrape_runs", ["scraper"])
    op.create_index("ix_scrape_runs_city_slug", "scrape_runs", ["city_slug"])

    # --- Seed: the synthetic 'national' city for the hal.gov.tr national bulletin ---
    op.execute(
        sa.text(
            "INSERT INTO cities (slug, name, source_type, source_url, enabled) "
            "VALUES ('national', 'Ulusal', 'hal_gov_tr', "
            "'https://www.hal.gov.tr/Sayfalar/FiyatDetaylari.aspx', true)"
        )
    )

    # --- Bootstrap prices_national so the API can query immediately --------
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS prices_national (
                id BIGSERIAL PRIMARY KEY,
                bulletin_date DATE NOT NULL,
                product_name TEXT NOT NULL,
                product_variety TEXT,
                product_category TEXT,
                average_price NUMERIC(12,4) NOT NULL,
                transaction_volume BIGINT,
                unit_name TEXT NOT NULL,
                last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_prices_national_bulletin_product
                    UNIQUE (bulletin_date, product_name, product_variety, product_category, unit_name)
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_prices_national_bulletin_date "
            "ON prices_national (bulletin_date)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_prices_national_product_name "
            "ON prices_national (product_name)"
        )
    )

    # --- provinces --------------------------------------------------------
    op.create_table(
        "provinces",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("plate_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_provinces_slug"),
    )
    op.create_index("ix_provinces_slug", "provinces", ["slug"], unique=True)
    op.create_index("ix_provinces_plate_code", "provinces", ["plate_code"])

    # --- districts --------------------------------------------------------
    op.create_table(
        "districts",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("province_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["province_id"],
            ["provinces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("province_id", "slug", name="uq_districts_province_slug"),
    )
    op.create_index("ix_districts_province_id", "districts", ["province_id"])
    op.create_index("ix_districts_slug", "districts", ["slug"])

    # --- markets ----------------------------------------------------------
    # day_of_week is String(128) because the source ships comma-separated short forms
    # ("Pzt,Pazar") that we expand to full Turkish day names ("Pazartesi,Pazar"), which
    # can exceed 32 chars when several days are listed.
    #
    # Uniqueness key is (district_id, market_type, name) — without address — because
    # the source lists parenthetical sub-sections of the same market (e.g.
    # "MURATBEY SEMT PAZARI (BALIK BÖLÜMÜ)") that the scraper strips and folds into
    # a single logical market.
    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("district_id", sa.Integer(), nullable=False),
        sa.Column(
            "market_type",
            sa.String(length=32),
            nullable=False,
            server_default="semt_pazari",
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=True),
        sa.Column("day_of_week", sa.String(length=128), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geocoded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["district_id"],
            ["districts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "district_id",
            "market_type",
            "name",
            name="uq_markets_district_type_name",
        ),
    )
    op.create_index("ix_markets_district_id", "markets", ["district_id"])
    op.create_index("ix_markets_market_type", "markets", ["market_type"])


def downgrade() -> None:
    """Drop everything created by upgrade()."""
    op.drop_index("ix_markets_market_type", table_name="markets")
    op.drop_index("ix_markets_district_id", table_name="markets")
    op.drop_table("markets")
    op.drop_index("ix_districts_slug", table_name="districts")
    op.drop_index("ix_districts_province_id", table_name="districts")
    op.drop_table("districts")
    op.drop_index("ix_provinces_plate_code", table_name="provinces")
    op.drop_index("ix_provinces_slug", table_name="provinces")
    op.drop_table("provinces")
    op.execute(sa.text("DROP VIEW IF EXISTS prices_all"))
    op.execute(sa.text("DROP TABLE IF EXISTS prices_national"))
    op.drop_index("ix_scrape_runs_city_slug", table_name="scrape_runs")
    op.drop_index("ix_scrape_runs_scraper", table_name="scrape_runs")
    op.drop_table("scrape_runs")
    op.drop_index("ix_cities_slug", table_name="cities")
    op.drop_table("cities")
