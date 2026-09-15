"""Public API for user-submitted place suggestion requests.

A visitor can request that a market be **added** (pinning coordinates on the
map) or **updated** (referencing an existing market). Each request captures a
lightweight, password-less identity — first/last name, email, and location
(city = province, town = district) — deduplicated by email, plus a free-text
explanation. Requests are stored ``pending`` for an operator to review in the
database; nothing is applied to the ``markets`` table automatically.

Endpoint:
- ``POST /suggestions`` — create one pending suggestion (and upsert the user).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from local_bazaar.db import get_session
from local_bazaar.models import (
    District,
    Market,
    MarketType,
    PlaceSuggestion,
    Province,
    SuggestionStatus,
    SuggestionType,
)

router = APIRouter()

# Pragmatic email shape check. A full RFC 5322 validator (pydantic ``EmailStr``)
# would pull in the ``email-validator`` dependency; this regex is enough to
# reject obvious garbage for a no-auth contact field.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SuggestionCreate(BaseModel):
    """Body of a ``POST /suggestions`` request.

    Identity fields are always required. The remaining fields depend on
    ``suggestion_type``: an ``add`` needs ``name`` + ``latitude``/``longitude``;
    an ``update`` needs ``market_id``.
    """

    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    email: str = Field(..., max_length=320)
    # User's own location (city / town).
    user_province: str | None = Field(default=None, max_length=64)
    user_district: str | None = Field(default=None, max_length=64)

    suggestion_type: SuggestionType
    explanation: str = Field(..., min_length=1, max_length=2000)

    # update-only
    market_id: int | None = None
    # add-only (and optional corrections on update)
    name: str | None = Field(default=None, max_length=255)
    market_type: MarketType | None = None
    province: str | None = Field(default=None, max_length=64)
    district: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    # Honeypot: real users never see or fill this; bots tend to fill every field.
    website: str = ""

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        """Lowercase, trim, and shape-check the email.

        Args:
            v: Raw email string.

        Returns:
            The normalized (lowercased, trimmed) email.

        Raises:
            ValueError: If the value does not look like an email address.
        """
        email = v.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("invalid email address")
        return email


class SuggestionCreated(BaseModel):
    """Response body of ``POST /suggestions``."""

    id: int
    status: str


async def _province_id(session: AsyncSession, slug: str | None) -> int | None:
    """Resolve a province slug to its id.

    Args:
        session: Injected DB session.
        slug: Province slug, or ``None``/empty to skip.

    Returns:
        The province id, or ``None`` when no slug was supplied.

    Raises:
        HTTPException: 404 if a non-empty slug matches no province.
    """
    if not slug:
        return None
    row = (
        await session.execute(select(Province).where(col(Province.slug) == slug))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Province '{slug}' not found")
    return row.id


async def _district_id(
    session: AsyncSession, province_id: int | None, slug: str | None
) -> int | None:
    """Resolve a district slug (within a province, when known) to its id.

    Args:
        session: Injected DB session.
        province_id: Owning province id used to disambiguate the slug; ``None``
            falls back to the first slug match.
        slug: District slug, or ``None``/empty to skip.

    Returns:
        The district id, or ``None`` when no slug was supplied.

    Raises:
        HTTPException: 404 if a non-empty slug matches no district.
    """
    if not slug:
        return None
    stmt = select(District).where(col(District.slug) == slug)
    if province_id is not None:
        stmt = stmt.where(col(District.province_id) == province_id)
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"District '{slug}' not found")
    return row.id


@router.post("/suggestions", response_model=SuggestionCreated)
async def create_suggestion(
    body: SuggestionCreate,
    session: AsyncSession = Depends(get_session),
) -> SuggestionCreated:
    """Create one pending place-suggestion and upsert its submitter.

    Args:
        body: The suggestion payload (see :class:`SuggestionCreate`).
        session: Injected DB session.

    Returns:
        ``{id, status}`` for the newly created suggestion (status ``pending``).

    Raises:
        HTTPException: 400 if the honeypot is filled or required per-type fields
            are missing; 404 if a referenced province/district/market is unknown.
    """
    if body.website.strip():
        raise HTTPException(status_code=400, detail="Invalid submission")

    # Per-type required fields.
    market_id: int | None = None
    if body.suggestion_type == SuggestionType.ADD:
        if not (body.name and body.name.strip()):
            raise HTTPException(status_code=400, detail="A new place requires a name")
        if body.latitude is None or body.longitude is None:
            raise HTTPException(status_code=400, detail="A new place requires map coordinates")
    else:  # UPDATE
        if body.market_id is None:
            raise HTTPException(status_code=400, detail="An update requires a market to reference")
        market = (
            await session.execute(select(Market).where(col(Market.id) == body.market_id))
        ).scalar_one_or_none()
        if market is None:
            raise HTTPException(status_code=404, detail=f"Market '{body.market_id}' not found")
        market_id = market.id

    user_province_id = await _province_id(session, body.user_province)
    user_district_id = await _district_id(session, user_province_id, body.user_district)
    place_province_id = await _province_id(session, body.province)
    place_district_id = await _district_id(session, place_province_id, body.district)

    # Upsert the submitter by email; repeat submitters reuse one row and get
    # their latest name/location. Mirrors the page-views UPSERT pattern.
    user_id = (
        await session.execute(
            text(
                """
                INSERT INTO users (first_name, last_name, email, province_id, district_id)
                VALUES (:first, :last, :email, :pid, :did)
                ON CONFLICT (email) DO UPDATE
                  SET first_name = EXCLUDED.first_name,
                      last_name = EXCLUDED.last_name,
                      province_id = EXCLUDED.province_id,
                      district_id = EXCLUDED.district_id
                RETURNING id
                """
            ),
            {
                "first": body.first_name.strip(),
                "last": body.last_name.strip(),
                "email": body.email,
                "pid": user_province_id,
                "did": user_district_id,
            },
        )
    ).scalar_one()

    suggestion = PlaceSuggestion(
        user_id=int(user_id),
        suggestion_type=body.suggestion_type,
        status=SuggestionStatus.PENDING,
        market_id=market_id,
        proposed_name=(body.name.strip() if body.name else None),
        proposed_market_type=(str(body.market_type) if body.market_type else None),
        province_id=place_province_id,
        district_id=place_district_id,
        latitude=body.latitude,
        longitude=body.longitude,
        explanation=body.explanation.strip(),
    )
    session.add(suggestion)
    await session.flush()
    new_id = suggestion.id or 0
    await session.commit()
    return SuggestionCreated(id=new_id, status=str(SuggestionStatus.PENDING))
