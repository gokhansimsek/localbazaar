"""One-off harvester: dump every Turkish province + district from hal.gov.tr.

Run once to regenerate the static fixture that the
``0002_seed_tr_geography`` Alembic migration loads from. Re-run whenever
hal.gov.tr ships new ilçes (Turkish districts occasionally split or get
renamed).

Invocation (from the repo root):

    docker compose exec api python -m scripts.harvest_tr_geo

The script writes ``src/local_bazaar/data/tr_geo.json`` relative to this
file's parent, plus a plate-code map merged from a canonical list defined
below.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TypedDict

from local_bazaar.db import city_slug
from local_bazaar.scrapers.base import fetch_with_retry, http_client
from local_bazaar.scrapers.bazaar_locations import (
    URL,
    _extract_guid_prefix,
    _extract_hidden_fields,
    _extract_select_options,
    to_title_case_tr,
)

log = logging.getLogger("harvest_tr_geo")


class DistrictRow(TypedDict):
    """A single district within a province in the fixture JSON."""

    slug: str
    name: str


class ProvinceRow(TypedDict):
    """A single province with its districts in the fixture JSON."""

    slug: str
    name: str
    plate_code: int | None
    districts: list[DistrictRow]


# Canonical Turkish province plate codes (01-81). Keys are the slugged province
# name so we can join against whatever label hal.gov.tr returns without caring
# about diacritics. This map is authoritative; if hal.gov.tr ever returns a
# label that doesn't slug into one of these keys, we surface a warning.
_PLATE_CODES: dict[str, int] = {
    "adana": 1,
    "adiyaman": 2,
    "afyonkarahisar": 3,
    "agri": 4,
    "amasya": 5,
    "ankara": 6,
    "antalya": 7,
    "artvin": 8,
    "aydin": 9,
    "balikesir": 10,
    "bilecik": 11,
    "bingol": 12,
    "bitlis": 13,
    "bolu": 14,
    "burdur": 15,
    "bursa": 16,
    "canakkale": 17,
    "cankiri": 18,
    "corum": 19,
    "denizli": 20,
    "diyarbakir": 21,
    "edirne": 22,
    "elazig": 23,
    "erzincan": 24,
    "erzurum": 25,
    "eskisehir": 26,
    "gaziantep": 27,
    "giresun": 28,
    "gumushane": 29,
    "hakkari": 30,
    "hatay": 31,
    "isparta": 32,
    "mersin": 33,
    "istanbul": 34,
    "izmir": 35,
    "kars": 36,
    "kastamonu": 37,
    "kayseri": 38,
    "kirklareli": 39,
    "kirsehir": 40,
    "kocaeli": 41,
    "konya": 42,
    "kutahya": 43,
    "malatya": 44,
    "manisa": 45,
    "kahramanmaras": 46,
    "mardin": 47,
    "mugla": 48,
    "mus": 49,
    "nevsehir": 50,
    "nigde": 51,
    "ordu": 52,
    "rize": 53,
    "sakarya": 54,
    "samsun": 55,
    "siirt": 56,
    "sinop": 57,
    "sivas": 58,
    "tekirdag": 59,
    "tokat": 60,
    "trabzon": 61,
    "tunceli": 62,
    "sanliurfa": 63,
    "usak": 64,
    "van": 65,
    "yozgat": 66,
    "zonguldak": 67,
    "aksaray": 68,
    "bayburt": 69,
    "karaman": 70,
    "kirikkale": 71,
    "batman": 72,
    "sirnak": 73,
    "bartin": 74,
    "ardahan": 75,
    "igdir": 76,
    "yalova": 77,
    "karabuk": 78,
    "kilis": 79,
    "osmaniye": 80,
    "duzce": 81,
}


def _control_name(prefix: str, leaf: str) -> str:
    """Build an ASP.NET control name like ``ctl00$ctl37$g_<guid>$ddlIl``."""
    return f"{prefix}${leaf}"


async def harvest() -> list[ProvinceRow]:
    """Fetch every province and its districts from hal.gov.tr.

    Returns:
        A list of :class:`ProvinceRow` dicts sorted by plate code
        (provinces with no plate-code mapping go last; ties break by name).
    """
    out: list[ProvinceRow] = []
    async with http_client() as client:
        initial = await fetch_with_retry(client, "GET", URL)
        html = initial.text
        prefix = _extract_guid_prefix(html)
        if prefix is None:
            raise RuntimeError("Could not discover form prefix on initial GET.")

        provinces = _extract_select_options(html, "ddlIl")
        log.info("Discovered %d provinces.", len(provinces))

        for prov_value, prov_label in provinces:
            pretty_prov = to_title_case_tr(prov_label)
            slug_prov = city_slug(pretty_prov)
            plate = _PLATE_CODES.get(slug_prov)
            if plate is None:
                log.warning("No plate code for province slug=%s name=%s", slug_prov, pretty_prov)

            form = _extract_hidden_fields(html)
            form[_control_name(prefix, "ddlIl")] = prov_value
            form["__EVENTTARGET"] = _control_name(prefix, "ddlIl")
            form["__EVENTARGUMENT"] = ""
            resp = await fetch_with_retry(client, "POST", URL, data=form)
            prov_html = resp.text

            district_pairs = _extract_select_options(prov_html, "ddlIlce")
            districts: list[DistrictRow] = []
            for _val, dist_label in district_pairs:
                pretty_dist = to_title_case_tr(dist_label)
                districts.append({"slug": city_slug(pretty_dist), "name": pretty_dist})

            out.append(
                ProvinceRow(
                    slug=slug_prov,
                    name=pretty_prov,
                    plate_code=plate,
                    districts=districts,
                )
            )
            log.info("%s (%s): %d districts", pretty_prov, plate, len(districts))

            await asyncio.sleep(0.3)

    out.sort(key=lambda p: (p["plate_code"] if p["plate_code"] is not None else 999, p["name"]))
    return out


def _write_fixture(rows: list[ProvinceRow]) -> Path:
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
    """Harvest from hal.gov.tr and write the JSON fixture."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    rows = await harvest()
    out_path = _write_fixture(rows)
    n_districts = sum(len(p["districts"]) for p in rows)
    log.info("Wrote %s — %d provinces, %d districts.", out_path, len(rows), n_districts)


if __name__ == "__main__":
    asyncio.run(main())
