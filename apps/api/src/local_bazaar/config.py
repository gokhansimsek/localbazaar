"""Runtime configuration loaded from environment variables / .env."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime knobs for the API and scraper, populated from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = Field(
        default="postgresql+psycopg://local_bazaar:change_me_in_local_only@localhost:5432/local_bazaar",
        description="Async SQLAlchemy URL for PostgreSQL.",
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_log_level: str = "info"
    api_cors_origins: str = "http://localhost:3000"

    # When False (default), /docs, /redoc, and /openapi.json are all 404 so the
    # API surface is opaque to clients. Set to True in trusted environments
    # (local dev, internal tooling) where the interactive docs are useful.
    enable_api_docs: bool = False

    # Per-IP rate limit applied to every /api/* route. Format is
    # ``<count>/<window>`` understood by slowapi (e.g. ``"120/minute"``,
    # ``"5000/hour"``). Set very high or wide windows to effectively disable.
    api_rate_limit: str = "120/minute"

    scraper_user_agent: str = "local_bazaar/0.1"
    scraper_daily_hour: int = 2
    scraper_disable_scheduler: bool = False

    # Google Maps Platform API key used for server-side geocoding and the JS map widget.
    # Leave empty to disable geocoding (markets will be stored without lat/lng).
    google_maps_api_key: str = ""

    # Shared secret for the hidden /admin/suggestions review page. When empty
    # (the default) the admin API returns 503 so it can't be used unprotected.
    # Set ADMIN_TOKEN to a long random string to enable it.
    admin_token: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Split the comma-separated ``api_cors_origins`` env var into a list.

        Returns:
            The configured CORS allow-list with surrounding whitespace stripped
            and empty entries removed.
        """
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


settings = Settings()
