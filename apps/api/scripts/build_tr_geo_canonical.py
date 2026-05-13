"""Build the canonical Turkish provinces + districts fixture from a public dataset.

We pull `il.json` and `ilce.json` from the maintained
``volkansenturk/turkiye-iller-ilceler`` repository, then:

1. Drop the non-Türkiye row "MAĞUSA (KIBRIS)" (id=503).
2. Replace placeholder "MERKEZ" district names with the province name — the
   canonical Turkish naming for the central (merkez) ilçe of a province
   (e.g. Adıyaman's central district is "Adıyaman").
3. Title-case every name with Turkish-aware rules.
4. Sort provinces by plate code and districts by name.

The output overwrites ``src/local_bazaar/data/tr_geo.json``.

Invocation (from the repo root):

    docker compose exec api python scripts/build_tr_geo_canonical.py
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from local_bazaar.db import city_slug
from local_bazaar.scrapers.bazaar_locations import to_title_case_tr

log = logging.getLogger("build_tr_geo_canonical")

_IL_URL = "https://raw.githubusercontent.com/volkansenturk/turkiye-iller-ilceler/master/il.json"
_ILCE_URL = "https://raw.githubusercontent.com/volkansenturk/turkiye-iller-ilceler/master/ilce.json"


def _table_rows(blocks: list[dict]) -> list[dict]:
    """Return the row list out of a PHPMyAdmin-style export array.

    Args:
        blocks: The top-level array decoded from the GitHub JSON file.

    Returns:
        The ``data`` array from the first object whose ``type`` is ``"table"``.
    """
    for block in blocks:
        if block.get("type") == "table":
            return block["data"]
    raise RuntimeError("No table block found in source JSON.")


async def _fetch_json(client: httpx.AsyncClient, url: str) -> list[dict]:
    """GET a JSON URL and decode it."""
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def build() -> list[dict[str, object]]:
    """Fetch the source JSONs and assemble the cleaned fixture in memory.

    Returns:
        A list of ``{slug, name, plate_code, districts: [{slug, name}, ...]}``
        sorted by plate code (ascending).
    """
    async with httpx.AsyncClient() as client:
        il_blocks, ilce_blocks = await asyncio.gather(
            _fetch_json(client, _IL_URL),
            _fetch_json(client, _ILCE_URL),
        )

    il_rows = _table_rows(il_blocks)
    ilce_rows = _table_rows(ilce_blocks)

    # Provinces: drop the Cyprus entry and anything whose numeric id is outside 1..81.
    provinces: dict[int, str] = {}
    for row in il_rows:
        try:
            plate = int(row["id"])
        except KeyError, ValueError:
            continue
        if 1 <= plate <= 81:
            provinces[plate] = row["name"]
    if len(provinces) != 81:
        raise RuntimeError(f"Expected 81 Turkish provinces, got {len(provinces)}.")

    # Districts grouped by plate code (drop anything pointing at a non-1..81 il_id).
    districts_by_plate: dict[int, list[str]] = {p: [] for p in provinces}
    for row in ilce_rows:
        try:
            plate = int(row["il_id"])
        except KeyError, ValueError:
            continue
        if plate not in districts_by_plate:
            continue  # foreign / unknown il_id
        districts_by_plate[plate].append(row["name"])

    out: list[dict[str, object]] = []
    total = 0
    for plate in sorted(provinces):
        pretty_prov = to_title_case_tr(provinces[plate])
        slug_prov = city_slug(pretty_prov)
        districts: list[dict[str, str]] = []
        names = districts_by_plate[plate]
        for raw_name in names:
            # Replace placeholder "MERKEZ" with the province name (canonical convention).
            name = raw_name if raw_name.strip().upper() != "MERKEZ" else provinces[plate]
            pretty = to_title_case_tr(name)
            districts.append({"slug": city_slug(pretty), "name": pretty})
        districts.sort(key=lambda d: d["name"])
        out.append(
            {
                "slug": slug_prov,
                "name": pretty_prov,
                "plate_code": plate,
                "districts": districts,
            }
        )
        total += len(districts)
        log.info("%2d %s: %d districts", plate, pretty_prov, len(districts))

    log.info("Built fixture: %d provinces, %d districts.", len(out), total)
    return out


def _write_fixture(rows: list[dict[str, object]]) -> Path:
    """Write the JSON fixture next to the data package and return its path.

    Path resolution and file I/O are kept out of the async pipeline so the
    coroutine stays free of blocking ``pathlib`` calls (ruff ``ASYNC240``).

    Args:
        rows: Province rows to serialize.

    Returns:
        Absolute path of the written file.
    """
    out_path = (
        Path(__file__).resolve().parent.parent / "src" / "local_bazaar" / "data" / "tr_geo.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


async def main() -> None:
    """Build the fixture and write it to ``src/local_bazaar/data/tr_geo.json``."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    rows = await build()
    out_path = _write_fixture(rows)
    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    asyncio.run(main())
