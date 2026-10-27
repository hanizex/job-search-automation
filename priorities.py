"""
priorities.py - Mykola's 3-level location priority (26.10.2026), built on location_rules.py.

  1  high    Sofia on-site/hybrid, or fully remote
  2  medium  relocation within Europe, or a country that gives Ukrainians temporary protection
  3  low     needs a work visa, or temporary protection does not apply
  None       drop (Germany-only and Ukraine-only; unchanged from the 25.10 rules)

location_rules.py keeps its own 1-4 scale and its 28 tests; this module only translates it, so the
patch files stay exactly as shipped:
  location_rules 1 (Sofia / Bulgaria)                          -> 1
  location_rules 2 with no named place (Remote, EMEA, Europe)   -> 1   fully remote
  location_rules 2 with a named EU country or city              -> 2   incl. "Remote, Ireland": residency needed
  location_rules 3 (Switzerland, Norway, Iceland, Liechtenstein) -> 2   temporary protection applies
  location_rules 4 (UK, US, Canada, anything else, unreadable)  -> 3
A chunk that names a US/Canada/LATAM/APAC place ("US-Remote", "Remote - California") is 3 even though
it also says "remote". A multi-location string keeps its BEST priority.

Uses location_rules' chunk helpers (_chunks, _classify), which are module-private by naming only.
"""
import re

import location_rules as lr

# Members of the regions the brief excludes (United States, Canada, LATAM, APAC), matched as whole words
# so "us" cannot hit "Austria". poll_jobs.location_matches imports this same pattern.
NON_EU_MEMBERS = (
    "us", "usa", "u.s.", "u.s.a.", "washington d.c.", "dc",
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
    "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "san francisco", "sf", "nyc", "new york city", "seattle", "chicago", "boston", "austin", "denver",
    "los angeles", "atlanta", "miami", "mountain view", "santa clara", "san diego", "san jose", "palo alto",
    "ontario", "quebec", "british columbia", "alberta", "toronto", "vancouver", "montreal", "ottawa",
    "costa rica", "brazil", "mexico", "argentina", "colombia", "chile", "peru", "uruguay",
    "india", "singapore", "japan", "china", "korea", "philippines", "indonesia", "malaysia", "thailand",
    "vietnam", "new zealand", "sydney", "melbourne",
)
NON_EU_MEMBERS_RE = re.compile(
    r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in NON_EU_MEMBERS) + r")(?![a-z])", re.I)

_NAMED_PLACES = (lr._GERMANY | lr._UKRAINE | lr._BULGARIA | lr._PROTECTED_NON_EU | lr._EU
                 | set(lr._EU_CITIES) | lr._VISA)
_EU_WIDE = re.compile(r"\b(eu|eea|european union)\b", re.I)   # location_rules does not know "EU"

WIDE, BARE, PLACE = "wide", "bare", "place"


def _chunk_info(chunk):
    """-> (priority or lr._DROPPED, kind). kind says what the chunk is:
    WIDE   region-wide remote: EMEA, Europe, EU, Home based - EMEA, Worldwide  -> 1 on its own
    BARE   just "Remote", no place at all                                      -> 1 only if NOTHING else in the
           string names a place: the adapters join fields with ";", so in "Boston; Massachusetts; us; Remote"
           the bare "Remote" is the US-only qualifier of the places before it, not worldwide remote
    PLACE  anything that names or implies a place"""
    base = lr._classify(chunk)
    if base == lr._DROPPED:
        return lr._DROPPED, PLACE
    low = " " + chunk.lower().replace(",", " ").replace("(", " ").replace(")", " ") + " "
    non_eu = bool(NON_EU_MEMBERS_RE.search(chunk))
    named = any(f" {w} " in low for w in _NAMED_PLACES)
    if not named and not non_eu:
        if lr._REMOTE_EUROPE.search(low) or _EU_WIDE.search(low):
            return 1, WIDE
        if lr._REMOTE_ANY.search(low):
            return 1, BARE
    if base == lr._UNKNOWN or non_eu and base == 2:
        return 3, PLACE
    return {1: 1, 2: 2, 3: 2, 4: 3}[base], PLACE


def priority3(location_text):
    """1, 2 or 3 per the scale above, or None (drop). Unreadable text is 3, never a drop."""
    infos = [_chunk_info(c) for c in lr._chunks(location_text)]
    has_place = any(kind == PLACE for _, kind in infos)
    cands = [p for p, kind in infos
             if isinstance(p, int) and (kind in (WIDE, PLACE) or (kind == BARE and not has_place))]
    if cands:
        return min(cands)
    if any(p == lr._DROPPED for p, _ in infos):
        return None
    return 3


# 26.10: P3 (needs a visa, or temporary protection does not apply) is hidden until P1 and P2 run out
# (Mykola's decision). job_filters.classify drops P3 while this is False; set it True to show them again,
# sorted last with the label P3.
SHOW_P3 = False

LABELS = {1: "P1", 2: "P2", 3: "P3"}


def label(priority):
    return LABELS.get(priority, "?")
