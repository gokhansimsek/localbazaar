"""Page-view counter API.

Endpoints:
- ``POST /page-views`` — atomically increment the counter for one path and
  return the new total. Each ping from the frontend ``<PageViewCounter/>``
  component lands here.
- ``GET /page-views`` — list every tracked path with its current count, for
  any dashboards / admin views that want to display a leaderboard.

Paths are bucketed on the frontend side before submission — dynamic routes
like ``/products/Domates`` are sent as the literal template ``/products/[name]``
so the table stays small.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.db import get_session

log = logging.getLogger(__name__)

router = APIRouter()

# Public app routes we accept. New routes must be added here so a bug or
# abuse vector cannot fill the table with arbitrary garbage paths.
_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/prices",
        "/trends",
        "/markets",
        "/products/[name]",
        "/privacy",
    }
)

_PATH_RE = re.compile(r"^/[A-Za-z0-9_/\-\[\]]*$")


class PageViewIn(BaseModel):
    """Body of a ``POST /page-views`` request."""

    path: str = Field(..., min_length=1, max_length=256)


class PageViewOut(BaseModel):
    """One row of the ``page_views`` table as exposed by the API."""

    path: str
    visit_count: int
    first_visited_at: datetime
    last_visited_at: datetime


class PageViewIncrementOut(BaseModel):
    """Response body of ``POST /page-views`` — just the new total."""

    path: str
    visit_count: int


@router.post("/page-views", response_model=PageViewIncrementOut)
async def record_view(
    body: PageViewIn,
    session: AsyncSession = Depends(get_session),
) -> PageViewIncrementOut:
    """Atomically increment the counter for ``body.path`` and return the new total.

    Args:
        body: ``{path}`` — must match the project's allow-list of routes.
        session: Injected DB session.

    Returns:
        ``{path, visit_count}`` where ``visit_count`` is the count after this
        increment.

    Raises:
        HTTPException: 400 if ``path`` is not on the allow-list or fails the
            structural regex check.
    """
    path = body.path.strip()
    if not _PATH_RE.match(path) or path not in _ALLOWED_PATHS:
        raise HTTPException(status_code=400, detail="Unknown page path")

    # Single round-trip UPSERT with atomic increment. ``RETURNING`` gives us
    # the post-increment count without a follow-up SELECT.
    result = await session.execute(
        text(
            """
            INSERT INTO page_views (path, visit_count, last_visited_at)
            VALUES (:path, 1, NOW())
            ON CONFLICT (path) DO UPDATE
              SET visit_count = page_views.visit_count + 1,
                  last_visited_at = NOW()
            RETURNING visit_count
            """
        ),
        {"path": path},
    )
    new_count = result.scalar_one()
    await session.commit()
    return PageViewIncrementOut(path=path, visit_count=int(new_count))


@router.get("/page-views", response_model=list[PageViewOut])
async def list_views(session: AsyncSession = Depends(get_session)) -> list[PageViewOut]:
    """Return every tracked path with its count, sorted by ``visit_count`` DESC.

    Args:
        session: Injected DB session.

    Returns:
        A list of :class:`PageViewOut` records. Paths that have never been
        pinged are not present in the table and therefore not returned.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT path, visit_count, first_visited_at, last_visited_at
                FROM page_views
                ORDER BY visit_count DESC, path ASC
                """
            )
        )
    ).mappings().all()
    return [PageViewOut(**dict(r)) for r in rows]
