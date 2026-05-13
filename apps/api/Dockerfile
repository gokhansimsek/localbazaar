# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.14

# ---- Builder ----
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# uv (https://docs.astral.sh/uv/)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first for better layer caching. The ``playwright`` extra is
# needed for the Antalya scraper, which has to drive a headless Chromium
# because the source page is a Vue SPA.
COPY pyproject.toml ./
COPY uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --frozen --extra playwright 2>/dev/null \
    || uv sync --no-install-project --extra playwright

# Copy source and install the project itself.
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra playwright 2>/dev/null \
    || uv sync --extra playwright

# ---- Runtime ----
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1001 app

# Copy uv into runtime too so `uv run alembic ...` works for migrations and ad-hoc commands.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

# Install Chromium + its OS-level dependencies (libnss3, libatk-bridge2.0, ...)
# so the Antalya scraper can drive a headless browser. Browsers are written
# under PLAYWRIGHT_BROWSERS_PATH and chowned so the unprivileged `app` user
# can launch them at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN apt-get update \
    && /opt/venv/bin/python -m playwright install-deps chromium \
    && PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
       /opt/venv/bin/python -m playwright install chromium \
    && chown -R app:app /opt/playwright-browsers \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "local_bazaar.main:app", "--host", "0.0.0.0", "--port", "8000"]
