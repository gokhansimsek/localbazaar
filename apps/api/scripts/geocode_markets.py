"""Standalone Google Maps geocoder for markets with NULL lat/lng.

The bazaar_locations scraper intentionally does not call the Google API —
addresses come in fast and free from hal.gov.tr, while geocoding costs quota.
Run this script when you want to spend that quota and fill in coordinates.

Invocation (from the repo root):

    docker compose exec api python scripts/geocode_markets.py [--max=N]

Requirements:
- ``GOOGLE_MAPS_API_KEY`` must be set in the environment (the Compose service
  forwards it from ``.env``). Without a key the script exits with code 2.
- Existing rows with coordinates are skipped; the script only fills NULLs.

Defaults to at most 200 API calls per run (``--max``) so a runaway misuse
can't burn through a day's quota in one go.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from local_bazaar.config import settings
from local_bazaar.db import SessionLocal
from local_bazaar.geocoding import geocode_pending_markets

log = logging.getLogger("geocode_markets")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments for the script.

    Args:
        argv: Argument list without the program name (typically ``sys.argv[1:]``).

    Returns:
        Parsed namespace with a single ``max`` integer attribute.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max",
        type=int,
        default=200,
        help="Maximum number of Google API calls in this run (default: 200).",
    )
    return parser.parse_args(argv)


async def main(max_calls: int) -> int:
    """Run a single geocode pass over markets with NULL coordinates.

    Args:
        max_calls: Hard cap on Google API calls for this invocation.

    Returns:
        Number of markets newly geocoded.
    """
    if not settings.google_maps_api_key:
        log.error(
            "GOOGLE_MAPS_API_KEY is not set; aborting. Set it in .env (or the cluster Secret)."
        )
        return -1
    async with SessionLocal() as session:
        wrote = await geocode_pending_markets(session, max_calls=max_calls)
        log.info("Geocoded %d markets (max_calls=%d).", wrote, max_calls)
        return wrote


def cli() -> None:
    """Entry point used by ``python scripts/geocode_markets.py``."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = _parse_args(sys.argv[1:])
    result = asyncio.run(main(args.max))
    sys.exit(0 if result >= 0 else 2)


if __name__ == "__main__":
    cli()
