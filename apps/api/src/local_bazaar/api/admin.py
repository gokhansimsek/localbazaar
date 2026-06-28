"""Hidden admin API for reviewing place-suggestion requests.

Protected by a shared token (``ADMIN_TOKEN``) sent in the ``X-Admin-Token``
header. There is no link to this surface anywhere in the UI — the matching
``/admin/suggestions`` page is reached by typing the URL directly.

Endpoints (all under ``/api/admin``):
- ``GET  /admin/suggestions`` — list suggestions (default: pending).
- ``POST /admin/suggestions/{id}/approve`` — apply and mark approved.
- ``POST /admin/suggestions/{id}/reject``  — mark rejected (optional note).

"Approve" auto-applies: an ``add`` creates (or reuses) the ``markets`` row,
resolving the district from the dropped pin via reverse geocoding; an
``update`` applies the corrected coordinates when the suggestion carries them.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from local_bazaar.config import settings
from local_bazaar.db import city_slug, get_session
from local_bazaar.geocoding import reverse_geocode_admin_areas
from local_bazaar.models import (
    District,
    PlaceSuggestion,
    Province,
    SuggestionStatus,
    SuggestionType,
)

router = APIRouter()


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Reject the request unless a valid admin token is presented.

    Args:
        x_admin_token: Value of the ``X-Admin-Token`` request header.

    Raises:
        HTTPException: 503 when no token is configured (feature disabled);
            401 when the header is missing or does not match.
    """
    expected = settings.admin_token
    if not expected:
        raise HTTPException(status_code=503, detail="Admin interface is not configured")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")


class AdminSuggestionOut(BaseModel):
    """A suggestion enriched with submitter and reference details for review."""

    id: int
    suggestion_type: str
    status: str
    created_at: datetime
    first_name: str
    last_name: str
    email: str
    explanation: str
    proposed_name: str | None
    proposed_market_type: str | None
    latitude: float | None
    longitude: float | None
    market_id: int | None
    market_name: str | None
    province: str | None
    district: str | None
    review_note: str | None


class AdminActionResult(BaseModel):
    """Outcome of an approve/reject action."""

    id: int
    status: str
    market_id: int | None
    detail: str


class RejectIn(BaseModel):
    """Body of a reject request."""

    note: str | None = None


@router.get("/admin/suggestions", response_model=list[AdminSuggestionOut])
async def list_suggestions(
    status: str = "pending",
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[AdminSuggestionOut]:
    """List suggestions for review, most recent first.

    Args:
        status: Filter by status (``pending``/``approved``/``rejected``), or
            ``all`` for every row.
        _: Admin-token guard.
        session: Injected DB session.

    Returns:
        The matching suggestions joined with submitter and reference info.
    """
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT s.id, s.suggestion_type, s.status, s.created_at, s.explanation,
                           s.proposed_name, s.proposed_market_type, s.latitude, s.longitude,
                           s.market_id, s.review_note,
                           u.first_name, u.last_name, u.email,
                           m.name AS market_name,
                           p.name AS province, d.name AS district
                    FROM place_suggestions s
                    JOIN users u ON u.id = s.user_id
                    LEFT JOIN markets m ON m.id = s.market_id
                    LEFT JOIN provinces p ON p.id = s.province_id
                    LEFT JOIN districts d ON d.id = s.district_id
                    WHERE (:status = 'all' OR s.status = :status)
                    ORDER BY s.created_at DESC, s.id DESC
                    """
                ),
                {"status": status},
            )
        )
        .mappings()
        .all()
    )
    return [AdminSuggestionOut(**dict(r)) for r in rows]


async def _load_pending(session: AsyncSession, suggestion_id: int) -> PlaceSuggestion:
    """Load a suggestion that must still be pending.

    Args:
        session: Injected DB session.
        suggestion_id: Target suggestion id.

    Returns:
        The pending :class:`PlaceSuggestion`.

    Raises:
        HTTPException: 404 if not found; 409 if it is no longer pending.
    """
    suggestion = (
        await session.execute(
            select(PlaceSuggestion).where(col(PlaceSuggestion.id) == suggestion_id)
        )
    ).scalar_one_or_none()
    if suggestion is None:
        raise HTTPException(status_code=404, detail=f"Suggestion '{suggestion_id}' not found")
    if suggestion.status != SuggestionStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Suggestion is already {suggestion.status}")
    return suggestion


async def _resolve_district_id(session: AsyncSession, suggestion: PlaceSuggestion) -> int:
    """Find the district id for an ``add`` suggestion's pinned location.

    Prefers a district already stored on the suggestion; otherwise reverse
    geocodes the pin and matches the province/district names against the
    geography tables by Turkish-aware slug.

    Args:
        session: Injected DB session.
        suggestion: The ``add`` suggestion being approved.

    Returns:
        The resolved ``districts.id``.

    Raises:
        HTTPException: 422 when no known district can be resolved.
    """
    if suggestion.district_id is not None:
        return suggestion.district_id
    if suggestion.latitude is None or suggestion.longitude is None:
        raise HTTPException(status_code=422, detail="Suggestion has no coordinates to resolve")

    province_name, district_name = await reverse_geocode_admin_areas(
        suggestion.latitude, suggestion.longitude
    )
    if not province_name or not district_name:
        raise HTTPException(
            status_code=422,
            detail="Could not resolve a province/district from the pin — apply this one manually.",
        )
    province = (
        await session.execute(
            select(Province).where(col(Province.slug) == city_slug(province_name))
        )
    ).scalar_one_or_none()
    if province is None:
        raise HTTPException(status_code=422, detail=f"Unknown province '{province_name}'")
    district = (
        await session.execute(
            select(District).where(
                col(District.province_id) == province.id,
                col(District.slug) == city_slug(district_name),
            )
        )
    ).scalar_one_or_none()
    if district is None:
        raise HTTPException(status_code=422, detail=f"Unknown district '{district_name}'")
    return district.id or 0


@router.post("/admin/suggestions/{suggestion_id}/approve", response_model=AdminActionResult)
async def approve_suggestion(
    suggestion_id: int,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminActionResult:
    """Apply a pending suggestion to the markets data and mark it approved.

    Args:
        suggestion_id: Target suggestion id.
        _: Admin-token guard.
        session: Injected DB session.

    Returns:
        The action outcome with the affected market id.

    Raises:
        HTTPException: 404/409 from :func:`_load_pending`; 422 if an ``add``
            cannot be resolved to a known district.
    """
    suggestion = await _load_pending(session, suggestion_id)

    if suggestion.suggestion_type == SuggestionType.ADD:
        district_id = await _resolve_district_id(session, suggestion)
        market_type = suggestion.proposed_market_type or "semt_pazari"
        market_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO markets
                        (district_id, market_type, name, latitude, longitude,
                         geocoded_at, last_seen, created_at)
                    VALUES (:did, :mtype, :name, :lat, :lng, now(), now(), now())
                    ON CONFLICT (district_id, market_type, name)
                      DO UPDATE SET last_seen = now()
                    RETURNING id
                    """
                ),
                {
                    "did": district_id,
                    "mtype": market_type,
                    "name": suggestion.proposed_name,
                    "lat": suggestion.latitude,
                    "lng": suggestion.longitude,
                },
            )
        ).scalar_one()
        suggestion.market_id = int(market_id)
        detail = f"Created/updated market #{int(market_id)}"
    else:  # UPDATE
        market_id = suggestion.market_id
        if suggestion.latitude is not None and suggestion.longitude is not None:
            await session.execute(
                text(
                    """
                    UPDATE markets
                    SET latitude = :lat, longitude = :lng, geocoded_at = now()
                    WHERE id = :mid
                    """
                ),
                {"lat": suggestion.latitude, "lng": suggestion.longitude, "mid": market_id},
            )
            detail = f"Applied corrected coordinates to market #{market_id}"
        else:
            detail = "Marked approved; apply the described change manually"

    suggestion.status = SuggestionStatus.APPROVED
    suggestion.reviewed_at = datetime.now(UTC)
    await session.commit()
    return AdminActionResult(
        id=suggestion_id,
        status=str(SuggestionStatus.APPROVED),
        market_id=suggestion.market_id,
        detail=detail,
    )


@router.post("/admin/suggestions/{suggestion_id}/reject", response_model=AdminActionResult)
async def reject_suggestion(
    suggestion_id: int,
    body: RejectIn,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AdminActionResult:
    """Mark a pending suggestion rejected.

    Args:
        suggestion_id: Target suggestion id.
        body: Optional reviewer note.
        _: Admin-token guard.
        session: Injected DB session.

    Returns:
        The action outcome.

    Raises:
        HTTPException: 404/409 from :func:`_load_pending`.
    """
    suggestion = await _load_pending(session, suggestion_id)
    suggestion.status = SuggestionStatus.REJECTED
    suggestion.review_note = (body.note or "").strip() or None
    suggestion.reviewed_at = datetime.now(UTC)
    await session.commit()
    return AdminActionResult(
        id=suggestion_id,
        status=str(SuggestionStatus.REJECTED),
        market_id=suggestion.market_id,
        detail="Rejected",
    )
