"""seed Türkiye provinces and districts.

Revision ID: 0002_seed_tr_geography
Revises: 0001_initial_schema
Create Date: 2026-05-13

Idempotent seed of the 81 Turkish provinces and their 973 districts (ilçes)
into the ``provinces`` and ``districts`` tables created by 0001. The data
ships as a checked-in JSON fixture at
``src/local_bazaar/data/tr_geo.json`` so the migration has no network or
external dependencies. The fixture itself is regenerated via
``scripts/build_tr_geo_canonical.py`` whenever administrative divisions
change.

The merkez (central) district of a province is recorded under the province's
own name (e.g. Adıyaman → Adıyaman), matching modern Turkish administrative
naming. Cyprus / KKTC entries from the upstream source are filtered out.

Inserts use ``ON CONFLICT DO NOTHING`` keyed on the existing unique
constraints, so re-running the migration on a partly-populated database is
safe.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0002_seed_tr_geography"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fixture_path() -> Path:
    """Resolve the path to the bundled tr_geo.json fixture.

    Returns:
        Absolute path to the fixture, relative to this migration file.
    """
    return (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "local_bazaar"
        / "data"
        / "tr_geo.json"
    )


def upgrade() -> None:
    """Seed the 81 Türkiye provinces and their districts."""
    data = json.loads(_fixture_path().read_text(encoding="utf-8"))
    conn = op.get_bind()

    insert_province = sa.text(
        "INSERT INTO provinces (slug, name, plate_code) "
        "VALUES (:slug, :name, :plate_code) "
        "ON CONFLICT (slug) DO UPDATE "
        "SET name = EXCLUDED.name, plate_code = EXCLUDED.plate_code "
        "RETURNING id"
    )
    insert_district = sa.text(
        "INSERT INTO districts (province_id, slug, name) "
        "VALUES (:province_id, :slug, :name) "
        "ON CONFLICT (province_id, slug) DO UPDATE "
        "SET name = EXCLUDED.name"
    )

    for province in data:
        result = conn.execute(
            insert_province,
            {
                "slug": province["slug"],
                "name": province["name"],
                "plate_code": province["plate_code"],
            },
        )
        province_id = result.scalar_one()
        for district in province["districts"]:
            conn.execute(
                insert_district,
                {
                    "province_id": province_id,
                    "slug": district["slug"],
                    "name": district["name"],
                },
            )


def downgrade() -> None:
    """Reverse the seed by removing only the rows this migration inserted.

    The fixture is re-read so we delete the exact set we seeded — any
    districts or provinces added since (e.g. by the bazaar_locations scraper)
    are left in place. ``markets`` rows linked to a removed district are
    cascade-deleted by the FK; callers who care about preserving market
    data should not downgrade this migration.
    """
    data = json.loads(_fixture_path().read_text(encoding="utf-8"))
    conn = op.get_bind()
    delete_district = sa.text(
        "DELETE FROM districts WHERE province_id = "
        "(SELECT id FROM provinces WHERE slug = :prov_slug) "
        "AND slug = :slug"
    )
    delete_province = sa.text("DELETE FROM provinces WHERE slug = :slug")

    for province in data:
        for district in province["districts"]:
            conn.execute(
                delete_district,
                {"prov_slug": province["slug"], "slug": district["slug"]},
            )
        conn.execute(delete_province, {"slug": province["slug"]})
