"""FastAPI app entry point.

Wires up:
- CORS for the Next.js dev server
- slowapi per-IP rate limiting (configured via ``api_rate_limit``)
- Health check
- /api routers
- apscheduler lifecycle (started/stopped in the lifespan)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import Response

from local_bazaar import __version__
from local_bazaar.api import admin as admin_router
from local_bazaar.api import markets as markets_router
from local_bazaar.api import page_views as page_views_router
from local_bazaar.api import prices as prices_router
from local_bazaar.api import suggestions as suggestions_router
from local_bazaar.config import settings
from local_bazaar.scheduler import start_scheduler, stop_scheduler

# Per-IP rate limiter shared across the app. ``get_remote_address`` reads the
# client's IP from the connection (or the ``X-Forwarded-For`` header behind a
# trusted proxy). The default limit applies to every /api/* route via the
# SlowAPIMiddleware below; specific endpoints can override with their own
# ``@limiter.limit(...)`` decorator.
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.api_rate_limit])


async def _rate_limit_handler(request: Request, exc: Exception) -> Response:
    """Convert a slowapi ``RateLimitExceeded`` into a clean JSON 429 response.

    Writing our own handler avoids depending on slowapi's private
    ``_rate_limit_exceeded_handler`` (which trips type-checkers on
    ``reportPrivateUsage``) and lets us shape the response body the way the
    Next.js client expects.

    Args:
        request: The incoming HTTP request.
        exc: The exception slowapi raised. Anything other than
            ``RateLimitExceeded`` is re-raised so the framework's default 500
            path still applies.

    Returns:
        ``JSONResponse`` with status 429 and a ``Retry-After`` header in
        seconds.
    """
    if not isinstance(exc, RateLimitExceeded):
        raise exc
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded",
            "limit": str(exc.detail),
        },
        headers={"Retry-After": "60"},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the in-process scheduler at app startup and stop it at shutdown."""
    scheduler = None
    if not settings.scraper_disable_scheduler:
        scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            stop_scheduler(scheduler)


app = FastAPI(
    title="Semt Pazarı API",
    version=__version__,
    summary=(
        "Turkey neighborhood-markets platform. First feature: wholesale-market "
        "prices (daily and historical national bulletin); second: a map of "
        "neighborhood and producer markets."
    ),
    lifespan=lifespan,
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)

# Register the limiter on the app instance so slowapi middleware + handlers
# can find it. ``RateLimitExceeded`` is converted into a 429 by our
# :func:`_rate_limit_handler`.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    """Liveness probe consumed by Kubernetes readinessProbe / livenessProbe."""
    return {"status": "ok", "version": __version__}


app.include_router(prices_router.router, prefix="/api", tags=["prices"])
app.include_router(markets_router.router, prefix="/api", tags=["markets"])
app.include_router(page_views_router.router, prefix="/api", tags=["page-views"])
app.include_router(suggestions_router.router, prefix="/api", tags=["suggestions"])
app.include_router(admin_router.router, prefix="/api", tags=["admin"])
