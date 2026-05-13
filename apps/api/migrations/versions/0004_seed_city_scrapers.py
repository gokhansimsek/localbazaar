"""seed per-city hal-price scrapers in the cities registry.

Revision ID: 0004_seed_city_scrapers
Revises: 0003_widen_markets_address
Create Date: 2026-06-10

Inserts the nine target cities into the ``cities`` table with
``source_type='city_site'``. The scheduler reads this registry and, for each
enabled ``city_site`` row, imports ``local_bazaar.scrapers.cities.<slug>`` and
calls its module-level ``run(session)``.

Inserts use ``ON CONFLICT (slug) DO NOTHING`` so re-running is safe.

Per-city ``prices_<slug>`` tables are NOT created here. They are created on
demand by :func:`local_bazaar.db.ensure_city_table` the first time a scraper
writes a row, so the migration stays orthogonal to scraper liveness.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_seed_city_scrapers"
down_revision: str | Sequence[str] | None = "0003_widen_markets_address"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (slug, display_name, source_url). source_type is city_site for all.
_CITIES: tuple[tuple[str, str, str], ...] = (
    ("adana", "Adana", "https://www.adana.bel.tr/tr/hal-fiyat-listesi"),
    ("ankara", "Ankara", "https://www.ankara.bel.tr/hal-fiyatlari"),
    ("antalya", "Antalya", "https://www.antalya.bel.tr/tr/halden-gunluk-fiyatlar"),
    ("bursa", "Bursa", "https://www.bursa.bel.tr/hal_fiyatlari"),
    ("istanbul", "İstanbul", "https://tarim.ibb.istanbul/tr/istatistik/124/hal-fiyatlari.html"),
    ("izmir", "İzmir", "https://eislem.izmir.bel.tr/tr/HalFiyatlari/"),
    ("kocaeli", "Kocaeli", "https://www.kocaeli.bel.tr/hal-fiyatlari/"),
    ("konya", "Konya", "https://www.konya.bel.tr/hal-fiyatlari"),
    ("sanliurfa", "Şanlıurfa", "https://halfiyatlari.sanliurfa.bel.tr/"),
)


def upgrade() -> None:
    """Insert the nine per-city scraper rows. Idempotent via ON CONFLICT DO NOTHING."""
    for slug, name, url in _CITIES:
        op.execute(
            sa.text(
                "INSERT INTO cities (slug, name, source_type, source_url, enabled) "
                "VALUES (:slug, :name, 'city_site', :url, true) "
                "ON CONFLICT (slug) DO NOTHING"
            ).bindparams(slug=slug, name=name, url=url)
        )


def downgrade() -> None:
    """Remove the per-city scraper rows. Per-city tables (if created) are left in place."""
    slugs = tuple(s for s, _, _ in _CITIES)
    op.execute(
        sa.text("DELETE FROM cities WHERE slug = ANY(:slugs) AND source_type = 'city_site'")
        .bindparams(sa.bindparam("slugs", value=list(slugs), expanding=True))
    )
