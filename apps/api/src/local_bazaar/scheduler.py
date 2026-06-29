"""Daily scrape scheduler.

Lives in-process with the FastAPI app. If/when scraping outgrows the API pod, this same
function can be invoked from a Kubernetes CronJob instead (the job code does not depend on
FastAPI being up).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from local_bazaar.config import settings
from local_bazaar.db import SessionLocal, ensure_city_table, prices_table
from local_bazaar.models import City, CitySourceType, ScrapeRun, ScrapeRunStatus

log = logging.getLogger(__name__)


def start_scheduler() -> AsyncIOScheduler:
    """Create, register, and start the daily scrape scheduler.

    Returns:
        The running :class:`AsyncIOScheduler` instance. Pass it back to
        :func:`stop_scheduler` at shutdown.
    """
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(
        run_daily_scrape,
        CronTrigger(hour=settings.scraper_daily_hour, minute=0),
        id="daily_scrape",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info(
        "Scheduler started — daily scrape at %02d:00 Europe/Istanbul.",
        settings.scraper_daily_hour,
    )
    return scheduler


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Shut the scheduler down without waiting for in-flight jobs to finish.

    Args:
        scheduler: The scheduler returned by :func:`start_scheduler`.
    """
    scheduler.shutdown(wait=False)


async def run_daily_scrape() -> None:
    """Run the national scrape, every per-city scraper, and the markets crawl.

    Geocoding is intentionally NOT part of the daily job — run it manually via
    ``scripts/geocode_markets.py`` when you want to spend Google API quota.

    Per-scrape errors do not crash the job — they are logged and recorded in
    the ``scrape_runs`` table for later inspection.
    """
    # Imported lazily to avoid pulling httpx into the API import path at startup.
    from local_bazaar.scrapers.bazaar_locations import BazaarLocationsScraper
    from local_bazaar.scrapers.hal_gov_tr import HalGovTrScraper

    async with SessionLocal() as session:
        cities = (
            (await session.execute(select(City).where(col(City.enabled).is_(True)))).scalars().all()
        )

        # National bulletin first — it produces rows for many cities at once.
        await _safe_scrape(session, "hal_gov_tr", None, HalGovTrScraper().run)

        for city in cities:
            if city.source_type == CitySourceType.CITY_SITE and city.source_url:
                # Per-city scrapers live under scrapers/cities/<slug>.py and expose run().
                module_name = f"local_bazaar.scrapers.cities.{city.slug}"
                try:
                    module = __import__(module_name, fromlist=["run"])
                except ModuleNotFoundError:
                    log.warning(
                        "No per-city scraper for %s (%s) — skipping.", city.slug, module_name
                    )
                    continue
                await _safe_scrape(session, city.slug, city.slug, module.run)

        # Markets: structural data (locations don't change daily) but cheap enough to
        # re-run every cycle to pick up new openings / closings. Geocoding is
        # intentionally NOT triggered here — it costs Google API quota and is
        # run on-demand via ``scripts/geocode_markets.py``.
        await _safe_scrape(session, "bazaar_locations", None, BazaarLocationsScraper().run)


async def _safe_scrape(
    session: AsyncSession,
    scraper_name: str,
    city_slug: str | None,
    fn: Callable[[AsyncSession], Awaitable[int]],
) -> None:
    """Run a single scraper call inside a ``scrape_runs`` audit record.

    Catches any exception raised by ``fn`` and records it as a failed run so
    the scheduler keeps going even when individual sources break.

    Args:
        session: An open async DB session.
        scraper_name: Human-readable scraper identifier (e.g. ``"hal_gov_tr"``).
        city_slug: City slug this scrape targets, or ``None`` for the national one.
        fn: Async callable that does the actual scrape and returns the number of
            rows written.
    """
    run = ScrapeRun(scraper=scraper_name, city_slug=city_slug)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    try:
        rows_written = await fn(session)
        run.status = ScrapeRunStatus.OK
        run.rows_written = rows_written or 0
    except Exception as exc:  # scheduled job must catch broadly so it does not crash
        log.exception("Scrape '%s' failed", scraper_name)
        run.status = ScrapeRunStatus.FAILED
        run.error = str(exc)[:1900]
    finally:
        run.finished_at = datetime.now(UTC)
        await session.commit()


def today_istanbul() -> date:
    """Return today's date in Europe/Istanbul.

    Returns:
        Today's calendar date according to the Turkish business day.
    """
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Istanbul")).date()


__all__ = [
    "ensure_city_table",
    "prices_table",
    "run_daily_scrape",
    "start_scheduler",
    "stop_scheduler",
    "today_istanbul",
]


async def _main() -> None:
    """Run the full daily scrape once and exit.

    This is the entrypoint the Kubernetes ``scrape-daily`` CronJob invokes
    (``python -m local_bazaar.scheduler``). It runs the same work the
    in-process scheduler would — national bulletin, every per-city scraper,
    and the markets crawl — without starting apscheduler, so the process
    exits when the scrape finishes. Geocoding is intentionally excluded
    (run ``scripts/geocode_markets.py`` separately).
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    await run_daily_scrape()


if __name__ == "__main__":
    asyncio.run(_main())
