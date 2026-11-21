"""
priorities.py - the 3-level location priority, built on location_rules.py and the search profile.

  1  high    home (on-site or hybrid), or fully remote
  2  medium  relocation within your relocation zones
  3  low     needs a work visa, or the place is in none of your zones
  None       drop (excluded places only)

location_rules.py keeps its own 1-4 scale; this module translates it:
  location_rules 1 (home)                                         -> 1
  location_rules 2 with no named place (Remote, EMEA, Europe)      -> 1   fully remote
  location_rules 2 with a named relocation place                   -> 2   incl. "Remote, Ireland": residency needed
  location_rules 3 (secondary relocation zone)                     -> 2
  location_rules 4 (any other named place, anything unreadable)    -> 3
A chunk that names a place scoped away from the home region ("US-Remote", "Remote - California") is 3 even
though it also says "remote" (profile: location.scoped_out). A multi-location string keeps its BEST priority.

Uses location_rules' chunk helpers (_chunks, _classify), which are module-private by naming only.
"""
import search_profile as _profile
import location_rules as lr


class _Markers:
    """Whole-word pattern of the places that scope a remote job away from the home region.
    Kept as an object with .search() so older callers (poll_jobs) work unchanged; the pattern follows the active profile."""

    def search(self, text):
        rx = _profile.compiled().marker_re
        return rx.search(text) if rx else None


NON_EU_MEMBERS_RE = _Markers()

WIDE, BARE, PLACE = "wide", "bare", "place"


def _eu_wide_search(low):
    rx = _profile.compiled().eu_wide_re
    return rx.search(low) if rx else None


def _named(low):
    return any(f" {w} " in low for w in _profile.compiled().all_tokens)


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
    named = _named(low)
    if not named and not non_eu:
        if lr.wide_search(low) or _eu_wide_search(low):
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


# P3 (needs a visa, or the place is in none of your zones) is hidden until P1 and P2 run out. The profile can
# switch it on (location.show_p3); job_filters.classify shows P3 when either this flag or the profile says so.
SHOW_P3 = False

LABELS = {1: "P1", 2: "P2", 3: "P3"}


def label(priority):
    return LABELS.get(priority, "?")
