"""
Location priority for the engine - replaces the relocation watch. Standard library only, Python 3.9+.

The places themselves come from the search profile (profile.py) and the geography catalogue (geo/places.json),
so any home country works. Scale used inside this module:

    1  home: the home country or one of its places
    2  relocation zone (location.relocation)
    3  secondary relocation zone (location.relocation_secondary)
    4  everything else that names a place: needs a work visa
    drop  excluded places (location.excluded)

A row with several locations keeps the BEST (lowest) priority among them, and is dropped only when EVERY
location is excluded. That is what stops an excluded country in a ten-country listing from killing an
otherwise good job. priorities.py turns this 1-4 scale into the three P-levels shown to the user.
"""
import re

import search_profile as _profile

DROP = None

# "remote" on its own, or tied to the home region, is priority 2 here. Tied to a country, the country decides,
# so these markers are only consulted when nothing else matched.
_REMOTE_ANY = re.compile(r"\b(remote|distributed|work\s*from\s*home|wfh)\b", re.I)

_SPLIT = re.compile(r"\s*(?:;|\||\bor\b|/(?!\s*hybrid))\s*", re.I)


def _cfg():
    return _profile.compiled()


def wide_search(low):
    """Region-wide remote words of the home region (for a European home: EMEA, Europe, Worldwide, Anywhere...)."""
    rx = _cfg().wide_re
    return rx.search(low) if rx else None


def _chunks(text):
    parts = [p.strip(" ,.()-") for p in _SPLIT.split(text or "")]
    return [p for p in parts if p]


_DROPPED = "drop"      # this chunk is an excluded place
_UNKNOWN = "unknown"   # no rule matched this chunk


def _classify(chunk):
    """One chunk -> priority int, _DROPPED, or _UNKNOWN."""
    c = _cfg()
    low = " " + chunk.lower().replace(",", " ").replace("(", " ").replace(")", " ") + " "

    def has(tokens):
        return any(f" {w} " in low for w in tokens)

    # Excluded places are checked first: they are drops wherever they appear.
    if has(c.excl_tokens):
        return _DROPPED
    if has(c.home_tokens):
        return 1
    if has(c.second_tokens):
        return 3
    if has(c.reloc_tokens):
        return 2
    if has(c.visa_tokens):
        return 4
    if wide_search(low):
        return 2
    if _REMOTE_ANY.search(low):
        return 2  # bare "Remote" with no country: assume home-region eligible, verify later
    return _UNKNOWN


def priority_for(location_text, default=4):
    """Best priority across every location in the string, or DROP (None).

    - Any chunk that resolves to 1-4 wins, lowest number first.
    - DROP only when every chunk is an excluded place.
    - A string we cannot read at all falls back to `default`, never to a drop.
    """
    chunks = _chunks(location_text)
    if not chunks:
        return default
    seen = [_classify(c) for c in chunks]
    numeric = [p for p in seen if isinstance(p, int)]
    if numeric:
        return min(numeric)
    if any(p == _DROPPED for p in seen):
        return DROP
    return default


def is_dropped(location_text):
    return priority_for(location_text, default=4) is DROP


def entity_risk(location_text):
    """True when a remote row names no home place.

    Not a drop. Some employers hire remotely only where they have an entity or PEO, and a row that never
    names the home country gives no sign it does. Flag it so the note can say: check whether they hire in
    the home country.
    """
    text = location_text or ""
    low = " " + text.lower() + " "
    if not _REMOTE_ANY.search(text) and not wide_search(low):
        return False
    return not any(_classify(c) == 1 for c in _chunks(text))


def explain(location_text):
    """Human-readable reason, for run.log."""
    p = priority_for(location_text)
    home = _cfg().home
    if p is DROP:
        return "drop: excluded place only"
    return {
        1: f"p1: home ({home})",
        2: "p2: relocation zone or remote",
        3: "p3: secondary relocation zone",
        4: "p4: work visa needed",
    }[p]
