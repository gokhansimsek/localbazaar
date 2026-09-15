"""Public API for newsletter signups from the site footer.

Endpoint:
- ``POST /newsletter`` — store one opted-in email address.

Only the address and signup time are stored; sending newsletters is out of
scope here. The response is identical whether the address is new or already
subscribed, so the endpoint cannot be used to probe which emails are on the
list.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from local_bazaar.db import get_session

router = APIRouter()

# Same pragmatic shape check as the suggestions endpoint: enough to reject
# obvious garbage without pulling in the email-validator dependency.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NewsletterSignup(BaseModel):
    """Body of a ``POST /newsletter`` request."""

    email: str = Field(..., max_length=320)
    # Must be True: the form's consent checkbox is the legal basis for storing
    # the address (KVKK / GDPR).
    consent: bool
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


class NewsletterSignupOut(BaseModel):
    """Response body of ``POST /newsletter``."""

    status: str


@router.post("/newsletter", response_model=NewsletterSignupOut)
async def subscribe(
    body: NewsletterSignup,
    session: AsyncSession = Depends(get_session),
) -> NewsletterSignupOut:
    """Store an opted-in newsletter signup.

    Args:
        body: The signup payload (see :class:`NewsletterSignup`).
        session: Injected DB session.

    Returns:
        ``{"status": "subscribed"}`` for both new and already-subscribed
        addresses.

    Raises:
        HTTPException: 400 if the honeypot is filled or consent was not given.
    """
    if body.website.strip():
        raise HTTPException(status_code=400, detail="Invalid submission")
    if not body.consent:
        raise HTTPException(status_code=400, detail="Consent is required to subscribe")

    await session.execute(
        text(
            """
            INSERT INTO newsletter_subscribers (email)
            VALUES (:email)
            ON CONFLICT (email) DO NOTHING
            """
        ),
        {"email": body.email},
    )
    await session.commit()
    return NewsletterSignupOut(status="subscribed")
