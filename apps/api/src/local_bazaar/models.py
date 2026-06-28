"""ORM models.

The registry tables (cities, scrape_runs, provinces, districts, markets) are modeled
as SQLModel classes. Per-city ``prices_*`` price tables are dynamic — see
``db.prices_table()``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Used as the Python-side default for ``server_default=func.now()`` columns so
    the model can be instantiated without explicit timestamps; the SQL
    ``server_default`` still applies for raw inserts that bypass the ORM.

    Returns:
        Current UTC time with ``tzinfo=timezone.utc``.
    """
    return datetime.now(UTC)


class CitySourceType(StrEnum):
    """Where a city's data is sourced from."""

    HAL_GOV_TR = "hal_gov_tr"  # national bulletin
    CITY_SITE = "city_site"  # per-city scraper discovered via Google


class City(SQLModel, table=True):
    """Registry row for each city whose prices we track."""

    __tablename__ = "cities"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=128)
    # Stored as plain VARCHAR; CitySourceType is a StrEnum so values round-trip cleanly.
    source_type: CitySourceType = Field(
        default=CitySourceType.HAL_GOV_TR,
        sa_column=Column(String(32), nullable=False, default=CitySourceType.HAL_GOV_TR.value),
    )
    source_url: str | None = Field(default=None, max_length=512)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )


class Province(SQLModel, table=True):
    """A Turkish province ("il"). Source of truth: ``ddlIl`` on the markets page."""

    __tablename__ = "provinces"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=64)
    plate_code: int | None = Field(
        default=None, index=True
    )  # vehicle plate prefix, 1..81 when known
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )


class District(SQLModel, table=True):
    """A Turkish district ("ilçe"), child of a :class:`Province`."""

    __tablename__ = "districts"

    id: int | None = Field(default=None, primary_key=True)
    province_id: int = Field(
        sa_column=Column(
            ForeignKey("provinces.id", ondelete="CASCADE"), nullable=False, index=True
        ),
    )
    slug: str = Field(index=True, max_length=64)
    name: str = Field(max_length=64)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )


class MarketType(StrEnum):
    """Kind of market published on hal.gov.tr/Sayfalar/Pazar-Yerleri.aspx."""

    SEMT_PAZARI = "semt_pazari"  # neighborhood market (Turkish source label)
    URETICI_PAZARI = "uretici_pazari"  # producer market (Turkish source label)


class Market(SQLModel, table=True):
    """One physical market place, geocoded for display on the map."""

    __tablename__ = "markets"
    # Matches the constraint created in migration 0001 so the model-built schema
    # (used by tests via create_all) agrees with the migrated DB and supports
    # ``ON CONFLICT (district_id, market_type, name)`` upserts.
    __table_args__ = (
        UniqueConstraint(
            "district_id", "market_type", "name", name="uq_markets_district_type_name"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    district_id: int = Field(
        sa_column=Column(
            ForeignKey("districts.id", ondelete="CASCADE"), nullable=False, index=True
        ),
    )
    market_type: MarketType = Field(
        default=MarketType.SEMT_PAZARI,
        sa_column=Column(
            String(32), nullable=False, index=True, default=MarketType.SEMT_PAZARI.value
        ),
    )
    name: str = Field(max_length=255)
    # Some real-world hal.gov.tr addresses run several hundred chars (e.g. İstanbul
    # bazaar locations spell out a full list of bordering streets), so use TEXT.
    address: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # Comma-separated full day names ("Pazartesi,Cuma"); source ships short forms
    # that the scraper expands.
    day_of_week: str | None = Field(default=None, max_length=128)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    geocoded_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_seen: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )


class ScrapeRunStatus(StrEnum):
    """Terminal status of a single scrape attempt."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class ScrapeRun(SQLModel, table=True):
    """Audit row for every scrape attempt — used by /healthz and the UI for staleness banners."""

    __tablename__ = "scrape_runs"

    id: int | None = Field(default=None, primary_key=True)
    scraper: str = Field(max_length=64, index=True)
    city_slug: str | None = Field(default=None, max_length=64, index=True)
    bulletin_date: str | None = Field(
        default=None, max_length=16
    )  # ISO date as text for portability
    status: ScrapeRunStatus = Field(
        default=ScrapeRunStatus.OK,
        sa_column=Column(String(16), nullable=False, default=ScrapeRunStatus.OK.value),
    )
    rows_written: int = Field(default=0)
    error: str | None = Field(default=None, max_length=2000)
    started_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class User(SQLModel, table=True):
    """A lightweight site user who submits place suggestions.

    There is no authentication: identity is captured per submission and
    deduplicated by email (UPSERT on the unique ``email`` column). Location is
    "city" (province) and "town" (district), held as nullable FKs.
    """

    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    first_name: str = Field(max_length=128)
    last_name: str = Field(max_length=128)
    # Stored lowercased; unique so repeat submitters reuse one row (ON CONFLICT).
    email: str = Field(sa_column=Column(Text, nullable=False, unique=True, index=True))
    province_id: int | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("provinces.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    district_id: int | None = Field(
        default=None,
        sa_column=Column(
            ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )


class SuggestionType(StrEnum):
    """Whether a suggestion adds a new market or updates an existing one."""

    ADD = "add"
    UPDATE = "update"


class SuggestionStatus(StrEnum):
    """Review state of a place suggestion."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PlaceSuggestion(SQLModel, table=True):
    """A user-submitted request to add or update a market place.

    Stored ``pending``; an operator reviews and applies it in the database.
    An ``add`` request carries the ``proposed_*`` fields plus pinned
    coordinates; an ``update`` request references an existing ``markets`` row
    via ``market_id``. Both kinds carry a free-text ``explanation``.
    """

    __tablename__ = "place_suggestions"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    )
    suggestion_type: SuggestionType = Field(sa_column=Column(String(16), nullable=False))
    status: SuggestionStatus = Field(
        default=SuggestionStatus.PENDING,
        sa_column=Column(
            String(16), nullable=False, index=True, default=SuggestionStatus.PENDING.value
        ),
    )
    # Set for an ``update`` request; SET NULL keeps the suggestion if the
    # referenced market row is later removed.
    market_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("markets.id", ondelete="SET NULL"), nullable=True, index=True),
    )
    proposed_name: str | None = Field(default=None, max_length=255)
    proposed_market_type: str | None = Field(default=None, max_length=32)
    province_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("provinces.id", ondelete="SET NULL"), nullable=True),
    )
    district_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("districts.id", ondelete="SET NULL"), nullable=True),
    )
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    explanation: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
    reviewed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    review_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
