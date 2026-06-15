"""Normalize raw scraper (name, variety) tuples into the ``products`` taxonomy.

The hal.gov.tr national bulletin and the per-city scrapers each surface their
own conventions for naming a product: duplication between ``product_name`` and
``product_variety``, parenthetical glosses ("(çikori)"), generic descriptor
modifiers ("Beyaz", "Taze"), Turkish I/İ casing quirks, and a long tail of
data-specific edge cases that no heuristic can guess.

This module owns the canonical mapping. It is consumed by:

- :mod:`migrations.versions.0006_products` — initial seed from
  ``prices_national`` distinct rows.
- :mod:`migrations.versions.0007_prices_product_id` — backfill of the
  per-city ``prices_<slug>`` ``product_id`` FK column.
- The runtime scraper UPSERT path (later) — when scrapers stop writing
  ``product_name`` / ``product_variety`` and instead resolve a product row up
  front.

When a new edge case is identified, add an entry to one of the curated tables
below. The general heuristics are intentionally simple; specific overrides
absorb anything they can't capture.
"""

from __future__ import annotations

import re

_PAREN_BLOCK = re.compile(r"\s*\(([^)]*)\)\s*")

# Python's default ``str.lower("İ")`` returns the two-codepoint sequence
# ``"i" + U+0307 COMBINING DOT ABOVE``. The result visually equals plain
# ``"i"`` but is a distinct string, which breaks deduplication. The per-city
# scrapers historically used ``str.capitalize`` and have written this dirty
# form into ``prices_<slug>`` rows. We strip the codepoint after lowering so
# every comparison/lookup is on the clean form.
_COMBINING_DOT_ABOVE = "̇"

# Turkish casing — Python's default lower()/upper() get two mappings wrong:
#   - "İ" (U+0130) lowers to "i̇" (i + combining dot above) instead of clean "i".
#   - "I" (U+0049) lowers to "i" instead of "ı" (dotless).
# We pre-translate the four ambiguous characters and let .lower()/.upper()
# handle everything else (ç, ş, ğ, ü, ö are already mapped correctly).
_TR_PRE_LOWER = str.maketrans({"İ": "i", "I": "ı"})
_TR_PRE_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def _tr_lower(s: str) -> str:
    """Lowercase a string with Turkish I/İ rules.

    Strips the U+0307 ``COMBINING DOT ABOVE`` codepoint that Python's default
    ``str.lower()`` emits when it sees ``İ``. This also cleans up any input
    already polluted by a previous default-Python title-case pass (the
    per-city scrapers historically used ``str.capitalize`` which produced
    e.g. ``"Bi̇ber"`` for ``"BİBER"``).

    Args:
        s: Input string (any case).

    Returns:
        Lowercased string preserving Turkish dotted/dotless ``i`` semantics.
    """
    return s.translate(_TR_PRE_LOWER).lower().replace(_COMBINING_DOT_ABOVE, "")


def _tr_upper_first(c: str) -> str:
    """Uppercase a single character with Turkish I/İ rules.

    Args:
        c: A single character.

    Returns:
        The uppercased character.
    """
    return c.translate(_TR_PRE_UPPER).upper()


def _title_case_tr(s: str) -> str:
    """Title-case each whitespace-separated token using Turkish I/İ rules.

    Args:
        s: Input string.

    Returns:
        A string with the first character of every token uppercased and the
        rest lowercased per :func:`_tr_lower`. Empty input → ``""``.
    """
    out: list[str] = []
    for w in s.split():
        if not w:
            continue
        lowered = _tr_lower(w)
        out.append(_tr_upper_first(lowered[0]) + lowered[1:])
    return " ".join(out)


# --- Curated normalization tables ---------------------------------------------

# Multi-word names that stay as a single ``name`` (never split, even when both
# words are 2+ tokens).
_COMPOUND_NAMES: frozenset[str] = frozenset(
    {
        "Hindistan Cevizi",
        "Mizuna Otu",
        "Mercan Köşk",
        "Deniz Börülcesi",
        "Brüksel Lahanası",
        "Asma Yaprağı",
        "Defne Yaprağı",
        "Yıldız Meyvesi",
        "Yer Elması",
        "Soya Filizi",
        "Şevketi Bostan",
        "Kabak Çiçeği",
        "Frenk Üzümü",
        "Hardal Otu",
        "Kara Koruğu",
        "Kudret Narı",
        "Tere Filizi",
        "Limon Otu",
        "Yeni Dünya",
        "Yaban Mersini",
        # Persimmon — both "Trabzon Hurması" and "Cennet Elması" rows in
        # prices_national describe the same fruit; folded into one name.
        "Trabzon Hurması",
    }
)

# Tokens to drop entirely from name (never become variety).
_DROP_TOKENS: frozenset[str] = frozenset(
    {
        "Beyaz",
        "Kırmızı",
        "Yeşil",
        "Sarı",
        "Pembe",
        "Siyah",
        "Mor",
        "Sivri",
        "Taze",
        "Kuru",
        "Sera",
        "Diğer",
    }
)

# Tokens that become ``variety`` when found as second word of a two-word name.
_PROMOTE_TO_VARIETY: frozenset[str] = frozenset(
    {
        "Çarliston",
        "Dolmalık",
        "Kapya",
        "Salçalık",
        "Kıvırcık",
        "Göbekli",
        "Iceberg",
        "Beef",
        "Cherry",
        "Kokteyl",
        "Salkım",
    }
)

# Known species — when found as the first word of a multi-word name, the
# remaining words become the variety. Existing 2-word rules (drop tokens,
# promote-to-variety) run first; this is the fallback for unrecognized
# patterns like ``Elma Granny Smith`` or ``Erik Mürdüm Karaca``.
_SPECIES_PREFIXES: frozenset[str] = frozenset(
    {
        "Elma",
        "Armut",
        "Erik",
        "Üzüm",
        "Domates",
        "Biber",
        "Patates",
        "Patlıcan",
        "Soğan",
        "Salatalık",
        "Fasulye",
        "Bakla",
        "Bezelye",
        "Lahana",
        "Havuç",
        "Marul",
        "Kavun",
        "Karpuz",
        "Kayısı",
        "Şeftali",
        "Nektarin",
        "Kiraz",
        "Vişne",
        "Limon",
        "Mandalina",
        "Portakal",
        "Greyfurt",
        "Mantar",
        "Mısır",
    }
)

# Foreign-cultivar fixups. The Turkish lowercasing maps ``I → ı``, which
# corrupts English words (``SMITH → smıth``). When titlecase produces a token
# matching a key here, replace it with the canonical English spelling.
_FOREIGN_FIXUPS: dict[str, str] = {
    "Smıth": "Smith",
    "Pınk": "Pink",
    "Kıng": "King",
    "Hıbrıd": "Hybrid",
    "Stark": "Stark",
}


def _apply_foreign_fixups(s: str | None) -> str | None:
    """Restore canonical English spellings for foreign cultivar tokens.

    Args:
        s: A title-cased string (or ``None``).

    Returns:
        The same string with each token in :data:`_FOREIGN_FIXUPS` replaced
        by its canonical form. ``None`` round-trips to ``None``.
    """
    if s is None:
        return None
    return " ".join(_FOREIGN_FIXUPS.get(w, w) for w in s.split())


# Source names whose parenthetical content is the canonical name — promote
# the inner string, drop the wrapper. Keys are tr-lowercased.
_NAME_PARENS_AS_NAME: dict[str, str] = {
    "mersin(yaban mersini)": "Yaban Mersini",
    "mersin (yaban mersini)": "Yaban Mersini",
}

# Source names (parens-stripped, title-cased) whose parenthetical content
# should become the ``variety`` instead of being dropped.
_NAME_PARENS_AS_VARIETY: frozenset[str] = frozenset(
    {
        "Biber Salçalık",  # "Biber Salçalık (Kapya)" → name=Biber, variety=Kapya
    }
)


def _pair_key(name: str, variety: str) -> tuple[str, str]:
    """Normalized lookup key for source (name, variety) pair overrides.

    Args:
        name: Source name (any case).
        variety: Source variety (any case).

    Returns:
        A ``(lower_name, lower_variety)`` tuple, with Turkish I/İ handled
        correctly. Used so curated override keys match the source no matter
        what casing the input has.
    """
    return (_tr_lower(name), _tr_lower(variety))


# Exact (source_name, source_variety) pair → (output_name, output_variety).
# Keys are tr-lowercased via :func:`_pair_key`.
_SOURCE_PAIR_OVERRIDES: dict[tuple[str, str], tuple[str, str | None]] = {
    _pair_key("Brüksel", "Lahanası"): ("Brüksel Lahanası", None),
    _pair_key("Asma", "Yaprağı"): ("Asma Yaprağı", None),
    _pair_key("Defne", "Yaprağı"): ("Defne Yaprağı", None),
    _pair_key("Yıldız", "Meyvesi"): ("Yıldız Meyvesi", None),
    _pair_key("Yer", "Elması"): ("Yer Elması", None),
    _pair_key("Soya", "Filizi"): ("Soya Filizi", None),
    _pair_key("Şevketi", "Bostan"): ("Şevketi Bostan", None),
    _pair_key("Kabak", "Çiçeği"): ("Kabak Çiçeği", None),
    _pair_key("Frenk", "Üzümü"): ("Frenk Üzümü", None),
    _pair_key("Hardal", "Otu"): ("Hardal Otu", None),
    # Source has "Kaya Koruğu" combined — typo correction to canonical "Kara Koruğu".
    _pair_key("Kaya Koruğu", "Kaya Koruğu"): ("Kara Koruğu", None),
    _pair_key("Kudret", "Narı"): ("Kudret Narı", None),
    _pair_key("Tere", "Tere Filizi"): ("Tere Filizi", None),
    _pair_key("Hindistan", "Cevizi"): ("Hindistan Cevizi", None),
    # Persimmon — both "Trabzon, Cennet Elması" and "Trabzon, Hurması" rows in
    # prices_national describe the same fruit; folded into one canonical name.
    _pair_key("Trabzon", "Cennet Elması"): ("Trabzon Hurması", None),
    _pair_key("Trabzon", "Hurması"): ("Trabzon Hurması", None),
    _pair_key("Salatalık Turşuluk", "Salatalık Turşuluk (Kornişon)"): (
        "Salatalık",
        "Turşuluk Kornişon",
    ),
}


def _strip_parens(s: str) -> str:
    """Remove every ``(…)`` segment from a string and collapse extra spaces."""
    return _PAREN_BLOCK.sub(" ", s).strip()


def _extract_parens(s: str) -> str | None:
    """Return the contents of the first ``(…)`` segment in ``s``, if any."""
    m = _PAREN_BLOCK.search(s)
    return m.group(1).strip() if m else None


def _clean_variety(variety: str, name: str) -> str | None:
    """Normalize a variety string against a known ``name``.

    Strips parens, removes the species prefix if duplicated (``"Elma, Starking"``
    when name=``Elma`` → ``Starking``), drops generic descriptor tokens
    (``Beyaz``, ``Diğer``, …), and returns ``None`` if nothing meaningful is
    left.

    Args:
        variety: Raw variety string (any case).
        name: The canonical ``name`` the variety qualifies.

    Returns:
        A cleaned variety string, or ``None`` when the variety carries no
        information beyond the name.
    """
    v = _title_case_tr(_strip_parens(variety))
    if not v:
        return None
    if v == name:
        return None
    name_first = name.split()[0] if name else ""
    if name_first and (v.startswith(f"{name_first} ") or v.startswith(f"{name_first},")):
        v = v[len(name_first):].lstrip(", ")
    if not v:
        return None
    words = v.split()
    filtered = [w for w in words if w not in _DROP_TOKENS]
    cleaned = " ".join(filtered)
    if not cleaned or cleaned == name or cleaned in _DROP_TOKENS:
        return None
    return cleaned


def normalize(
    product_name: str | None,
    product_variety: str | None,
) -> tuple[str, str | None]:
    """Apply the project's product normalization rules.

    The full set of rules is described in this module's docstring; in summary:

    1. Exact ``(source_name, source_variety)`` pair overrides.
    2. Parens-as-name overrides (promote inner content as the canonical name).
    3. Parens-as-variety overrides (promote inner content as variety).
    4. Default: strip parens content from both sides (treat as gloss).
    5. ``_COMPOUND_NAMES`` keep-as-is.
    6. Two-word name analysis: drop descriptor tokens, promote variety tokens,
       reverse-order species swap, species inference from variety.
    7. Species-prefix split: when the first word is a known species, the
       remaining tokens become the variety.

    Args:
        product_name: Source ``product_name`` column.
        product_variety: Source ``product_variety`` column.

    Returns:
        A ``(name, variety)`` tuple. ``variety`` is ``None`` when the source
        carries no useful variant after normalization.
    """
    raw_name = (product_name or "").strip()
    raw_variety = (product_variety or "").strip()
    title_name = _title_case_tr(raw_name)
    title_variety = _title_case_tr(raw_variety) if raw_variety else ""

    # 1. Exact source pair override (case-insensitive lookup).
    pkey = _pair_key(raw_name, raw_variety)
    if pkey in _SOURCE_PAIR_OVERRIDES:
        return _SOURCE_PAIR_OVERRIDES[pkey]

    # 2. Parens content is the canonical name (Mersin → Yaban Mersini).
    #    Variety is dropped — when the wrapper is the source's idea of
    #    a variety, it's almost always a duplicate of the wrapper itself.
    lower_name = _tr_lower(raw_name)
    if lower_name in _NAME_PARENS_AS_NAME:
        return _NAME_PARENS_AS_NAME[lower_name], None

    # 3. Parens content should become the variety (Biber Salçalık (Kapya)).
    stripped_title = _title_case_tr(_strip_parens(raw_name))
    paren_content = _extract_parens(title_name)
    if stripped_title in _NAME_PARENS_AS_VARIETY and paren_content:
        species = stripped_title.split()[0]
        return species, _title_case_tr(paren_content) or None

    # 4. Default: parens content is a gloss, strip it from both sides.
    n = stripped_title
    v_clean = _clean_variety(raw_variety, n) if raw_variety else None

    # 5. Compound-name keep-as-is.
    if n in _COMPOUND_NAMES:
        return n, v_clean

    # 6. Two-word name analysis.
    words = n.split()
    if len(words) == 2:
        first, second = words
        if second in _DROP_TOKENS:
            return first, _apply_foreign_fixups(_clean_variety(raw_variety, first))
        if first in _DROP_TOKENS:
            return second, _apply_foreign_fixups(_clean_variety(raw_variety, second))
        if second in _PROMOTE_TO_VARIETY:
            cleaned = _clean_variety(raw_variety, first)
            return first, _apply_foreign_fixups(cleaned if cleaned else second)
        if first in _PROMOTE_TO_VARIETY:
            cleaned = _clean_variety(raw_variety, second)
            return second, _apply_foreign_fixups(cleaned if cleaned else first)
        # Reverse-order species: name="<modifier> <species>" with species in
        # the second slot (e.g. "Tatlı Patates" → name=Patates, variety=Tatlı).
        if second in _SPECIES_PREFIXES and first not in _SPECIES_PREFIXES:
            return second, _apply_foreign_fixups(first)
        # Species inference: when the variety's first token equals the name's
        # first token, treat the first token as the species.
        if title_variety:
            v_tokens = re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", title_variety)
            v_first = _title_case_tr(v_tokens[0]) if v_tokens else ""
            if v_first == first:
                return first, _apply_foreign_fixups(_clean_variety(raw_variety, first))

    # 7. Species-prefix split: covers 3+ word names like "Elma Granny Smith".
    if len(words) >= 2 and words[0] in _SPECIES_PREFIXES:
        species = words[0]
        rest = " ".join(words[1:])
        src_v = _clean_variety(raw_variety, species)
        return species, _apply_foreign_fixups(src_v if src_v else rest)

    return n, _apply_foreign_fixups(v_clean)


# --- Produce-only filter ------------------------------------------------------
#
# The platform scope is fruit + vegetable wholesale prices. Sources that bundle
# fish/seafood (hal.gov.tr ulusal, Ankara, Bursa) leak rows like "Hamsi" /
# "Levrek" into prices_<slug>; both scrapers and a one-time cleanup migration
# call :func:`is_fish_name` to discard them.

_FISH_NAMES: frozenset[str] = frozenset(
    {
        # Pelajik & dip / pelagic & demersal fish
        "Hamsi",
        "Sardalya",
        "Sardalye",
        "Palamut",
        "Bonito",
        "Lüfer",
        "Çinekop",
        "Kolyoz",
        "Uskumru",
        "İstavrit",
        "Kefal",
        "Levrek",
        "Çupra",
        "Çipura",
        "Sinarit",
        "Trança",
        "Mezgit",
        "Mercan",  # mercan balığı (distinct from "Mercan Köşk" which is the herb)
        "Barbun",  # barbun balığı (distinct from "Barbunya" the bean)
        "Tekir",
        "Lahoz",
        "Karagöz",
        "Sargoz",
        "Eşkina",
        "Lipsoz",
        "İzmarit",
        "Aterina",
        "Gelincik",
        "Kılıç",
        "Kalkan",
        "Vatoz",
        "Köpek Balığı",
        "Yılan Balığı",
        # Su ürünleri / shellfish & cephalopods
        "Karides",
        "Jumbo Karides",
        "Ahtapot",
        "Kalamar",
        "Midye",
        "Pavurya",
        "Yengeç",
        "Çağanoz",
        "Istakoz",
        "İstakoz",
        "Deniz Salyangozu",
        # Imported / farmed
        "Somon",
        "Norveç Somonu",
        "Alabalık",
        "Sazan",
        "Tirsi",
    }
)

# Substring patterns that strongly imply a fish/seafood product even when the
# canonical name above doesn't appear verbatim (e.g. ``"Hamsi Donmuş"`` or
# ``"Çipura Kültür"``). Matched after Turkish-aware lowering.
_FISH_SUBSTRINGS: tuple[str, ...] = (
    " balığı",
    "balık ",
    "balığı ",
)


# Turkish possessive / genitive suffixes that get appended to species words,
# e.g. ``Somon → Somonu``, ``Sazan → Sazanı``, ``Mercan → Mercanı``. Used by
# :func:`is_fish_name` to match suffixed forms without exploding the dictionary.
_TR_POSSESSIVE_SUFFIXES: tuple[str, ...] = ("u", "ü", "ı", "i", "su", "sü", "sı", "si", "ları", "leri")


def _fold_dotted_i(s: str) -> str:
    """Collapse Turkish dotted/dotless ``i`` variants to a single form.

    Turkish ALL-CAPS publications use ``I`` for both ``i`` and ``ı``
    ambiguously: ``HAMSI`` could be ``Hamsi`` or ``Hamsı``. For dictionary
    lookups we fold both lowercase forms onto ``i`` so the comparison
    succeeds either way.

    Args:
        s: A lowercase string.

    Returns:
        The same string with every ``ı`` replaced by ``i``.
    """
    return s.replace("ı", "i")


_FISH_NAMES_FOLDED: frozenset[str] = frozenset(
    _fold_dotted_i(_tr_lower(n)) for n in _FISH_NAMES
)


def is_fish_name(name: str | None) -> bool:
    """Return ``True`` when ``name`` is a fish, shellfish, or cephalopod.

    Source rows arrive in any case ("HAMSI", "Hamsi", "hamsi"), so the input
    is title-cased before the dictionary lookup. Matches against
    :data:`_FISH_NAMES` (any of the first four tokens), accepting Turkish
    possessive suffixes (``Somonu``, ``Sazanı``, …). Compound names that look
    fishy but aren't (``Mercan Köşk`` = sweet marjoram) are protected by an
    early-return against :data:`_COMPOUND_NAMES`. Used by every scraper that
    can't drop fish at the source level (hal.gov.tr is one big flat table)
    and by the cleanup migration that prunes legacy fish rows.

    Args:
        name: A product name. ``None`` returns ``False``.

    Returns:
        ``True`` when the name resolves to a fish/seafood product.
    """
    if not name:
        return False
    cleaned = name.strip()
    if not cleaned:
        return False
    titled = _title_case_tr(cleaned)
    if titled in _COMPOUND_NAMES:
        return False
    tokens = titled.split()
    for tok in tokens[:4]:
        folded_tok = _fold_dotted_i(_tr_lower(tok))
        if folded_tok in _FISH_NAMES_FOLDED:
            return True
        # Accept tokens that are a fish name + Turkish possessive suffix.
        for fn in _FISH_NAMES_FOLDED:
            if folded_tok != fn and folded_tok.startswith(fn):
                suffix = folded_tok[len(fn):]
                if suffix in _TR_POSSESSIVE_SUFFIXES:
                    return True
    lower = _tr_lower(cleaned)
    return any(s in lower for s in _FISH_SUBSTRINGS)


# --- Unit canonicalization ---------------------------------------------------
#
# The source data uses ~20 different spellings for the same handful of units:
# ``Kg``/``kg``/``KG``/``Kğ`` / ``Adet``/``adet``/``Ad`` / ``Bağ``/``bağ``/``BAĞ`` /
# ``Demet``/``demet``/``(Demet)`` / ``Paket``/``Koli``/``Kasa``/``Çuval``/``Sandık``.
# :func:`normalize_unit` collapses them to a canonical title-cased form and
# strips surrounding parens. Unrecognized inputs pass through with only
# whitespace and surrounding parens cleaned, so packaging tokens like
# ``Pk/125 G`` (Antalya) survive.

_UNIT_SYNONYMS: dict[str, str] = {
    "kg": "Kg",
    "kg.": "Kg",
    "kğ": "Kg",
    "kgs": "Kg",
    "adet": "Adet",
    "ad": "Adet",
    "ad.": "Adet",
    "bağ": "Bağ",
    "demet": "Demet",
    "paket": "Paket",
    "koli": "Koli",
    "kasa": "Kasa",
    "çuval": "Çuval",
    "sandık": "Sandık",
}


def normalize_unit(raw: str | None) -> str:
    """Canonicalize a unit string from any scraper.

    The default for empty input is ``Kg`` since that's the dominant unit in
    every source we ingest.

    Args:
        raw: Source ``unit_name`` (any case, possibly parenthesised).

    Returns:
        A canonical title-cased unit. Unknown inputs pass through with
        whitespace and surrounding ``( … )`` removed.
    """
    if not raw:
        return "Kg"
    s = raw.strip()
    if not s:
        return "Kg"
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    lower = _tr_lower(s)
    # Drop a "taze " (= "fresh ") prefix that some sources stamp onto units.
    lower = re.sub(r"^taze\s+", "", lower)
    if lower in _UNIT_SYNONYMS:
        return _UNIT_SYNONYMS[lower]
    # Unknown — return cleaned input as-is, preserving original casing for
    # packaging tokens like "Pk/125 G".
    return s


# --- Category canonicalization ----------------------------------------------
#
# Only the three quality grades published by hal.gov.tr's national bulletin
# are accepted as ``category`` values. Per-city scrapers write category-like
# strings into the same slot (Bursa tab labels "Meyve"/"Sebze", Ankara
# "İthal", or simply leave it NULL); we collapse all of those to
# ``Geleneksel(Konvansiyonel)`` so the taxonomy stays consistent across
# every source.

_VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "Geleneksel(Konvansiyonel)",
        "İyi Tarım",
        "Organik Tarım",
        "İthal",
    }
)

_DEFAULT_CATEGORY = "Geleneksel(Konvansiyonel)"


def normalize_category(raw: str | None) -> str:
    """Canonicalize a category value to one of the four accepted grades.

    Args:
        raw: Source ``product_category`` value, ``None``, or empty string.

    Returns:
        One of :data:`_VALID_CATEGORIES`. Anything not on the allow-list —
        including ``Meyve``, ``Sebze``, and ``NULL`` — collapses to
        :data:`_DEFAULT_CATEGORY` (``"Geleneksel(Konvansiyonel)"``). The
        legitimate ``İthal`` value is preserved.
    """
    if raw is None:
        return _DEFAULT_CATEGORY
    cleaned = raw.strip()
    if not cleaned:
        return _DEFAULT_CATEGORY
    if cleaned in _VALID_CATEGORIES:
        return cleaned
    return _DEFAULT_CATEGORY


def promote_category_words(
    name: str,
    variety: str | None,
    category: str,
) -> tuple[str, str | None, str]:
    """Move category-like words out of ``variety`` into the right slot.

    Some scrapers spell origin / trade tags inside the variety column when
    they really belong in the category slot — ``Muz / İthal``,
    ``Karpuz / İthal``, ``Muz / Yerli``, ``Muz / Yerli Anamur``. We strip the
    leaked token here so it can either re-classify the product (``İthal``)
    or get dropped entirely (``Yerli`` is the implicit default; the actual
    cultivar like ``Anamur`` is what we keep).

    Args:
        name: Canonical product name.
        variety: Variety from :func:`normalize` (post-canonicalization).
        category: Already-canonical category from :func:`normalize_category`.

    Returns:
        A possibly-rewritten ``(name, variety, category)`` triple.
    """
    if variety is None:
        return name, None, category
    v = variety.strip()
    if v == "İthal":
        return name, None, "İthal"
    if v == "Yerli":
        return name, None, category
    if v.startswith("Yerli "):
        rest = v[len("Yerli "):].strip()
        return name, rest or None, category
    return name, variety, category


__all__ = [
    "is_fish_name",
    "normalize",
    "normalize_category",
    "normalize_unit",
    "promote_category_words",
]
