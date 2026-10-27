"""
Location priority for Agent 1 — replaces the relocation watch.

New file, 25.10.2026. Standard library only, Python 3.9+.

Mykola's rule of 25.10:
    1  Sofia / Bulgaria
    2  Warsaw, any other EU country, or 100% remote
    3  non-EU with temporary protection: Switzerland, Norway, Iceland, Liechtenstein
    4  needs a work visa: United Kingdom, USA, Canada, everything else
    drop  Germany; Ukraine-only

A row with several locations keeps the BEST (lowest) priority among them, and is
dropped only when EVERY location is a drop. That is what stops a Germany entry in
a ten-country listing from killing an otherwise good job.
"""

import re

DROP = None

_EU = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czechia",
    "czech republic", "denmark", "estonia", "finland", "france", "greece",
    "hungary", "ireland", "italy", "latvia", "lithuania", "luxembourg",
    "malta", "netherlands", "poland", "portugal", "romania", "slovakia",
    "slovenia", "spain", "sweden",
}

_EU_CITIES = {
    "amsterdam": "netherlands", "rotterdam": "netherlands", "eindhoven": "netherlands",
    "warsaw": "poland", "warszawa": "poland", "krakow": "poland", "kraków": "poland",
    "wroclaw": "poland", "gdansk": "poland", "szczecin": "poland", "poznan": "poland",
    "dublin": "ireland", "cork": "ireland",
    "paris": "france", "lyon": "france", "toulouse": "france",
    "madrid": "spain", "barcelona": "spain", "valencia": "spain",
    "lisbon": "portugal", "porto": "portugal",
    "milan": "italy", "rome": "italy", "turin": "italy",
    "stockholm": "sweden", "gothenburg": "sweden",
    "copenhagen": "denmark", "helsinki": "finland", "tallinn": "estonia",
    "riga": "latvia", "vilnius": "lithuania", "kaunas": "lithuania",
    "prague": "czechia", "brno": "czechia", "bratislava": "slovakia",
    "budapest": "hungary", "bucharest": "romania", "cluj": "romania",
    "athens": "greece", "thessaloniki": "greece",
    "vienna": "austria", "brussels": "belgium", "luxembourg city": "luxembourg",
    "zagreb": "croatia", "ljubljana": "slovenia", "valletta": "malta",
    "limassol": "cyprus", "nicosia": "cyprus", "paphos": "cyprus",
}

_BULGARIA = {"bulgaria", "sofia", "plovdiv", "varna", "burgas", "ruse", "bgr"}

_PROTECTED_NON_EU = {
    "switzerland", "zurich", "zürich", "geneva", "basel", "bern", "lausanne",
    "norway", "oslo", "bergen", "trondheim",
    "iceland", "reykjavik", "reykjavík",
    "liechtenstein", "vaduz",
}

_GERMANY = {
    "germany", "deutschland", "berlin", "munich", "münchen", "hamburg",
    "frankfurt", "cologne", "köln", "stuttgart", "düsseldorf", "dusseldorf",
    "leipzig", "dresden", "nuremberg", "nürnberg", "erlangen", "walldorf", "ulm",
}

_UKRAINE = {"ukraine", "kyiv", "kiev", "lviv", "kharkiv", "odesa", "odessa", "dnipro"}

_VISA = {
    "united kingdom", "uk", "england", "scotland", "wales", "london",
    "manchester", "edinburgh", "cambridge", "bristol", "belfast",
    "united states", "usa", "u.s.", "canada", "toronto", "vancouver", "montreal",
    "israel", "tel aviv", "india", "bangalore", "bengaluru", "pune", "hyderabad",
    "japan", "tokyo", "singapore", "australia", "sydney", "melbourne",
    "brazil", "mexico", "argentina", "uae", "dubai", "turkey", "istanbul",
    "serbia", "belgrade", "armenia", "yerevan", "georgia", "tbilisi",
    "moldova", "chisinau", "albania", "north macedonia", "bosnia", "montenegro",
}

# "remote" on its own, or tied to Europe, is priority 2. Tied to a country, the
# country decides, so these markers are only consulted when nothing else matched.
_REMOTE_EUROPE = re.compile(
    r"\b(emea|europe|european|home\s*based|worldwide|global|anywhere)\b", re.I
)
_REMOTE_ANY = re.compile(r"\b(remote|distributed|work\s*from\s*home|wfh)\b", re.I)

_SPLIT = re.compile(r"\s*(?:;|\||\bor\b|/(?!\s*hybrid))\s*", re.I)


def _chunks(text):
    parts = [p.strip(" ,.()-") for p in _SPLIT.split(text or "")]
    return [p for p in parts if p]


_DROPPED = "drop"      # this chunk is Germany or Ukraine
_UNKNOWN = "unknown"   # no rule matched this chunk


def _classify(chunk):
    """One chunk -> priority int, _DROPPED, or _UNKNOWN."""
    low = " " + chunk.lower().replace(",", " ").replace("(", " ").replace(")", " ") + " "

    def has(words):
        return any(f" {w} " in low for w in words)

    # Germany and Ukraine are checked first: they are drops wherever they appear.
    if has(_GERMANY):
        return _DROPPED
    if has(_UKRAINE):
        return _DROPPED
    if has(_BULGARIA):
        return 1
    if has(_PROTECTED_NON_EU):
        return 3
    if has(_EU) or has(set(_EU_CITIES)):
        return 2
    if has(_VISA):
        return 4
    if _REMOTE_EUROPE.search(low):
        return 2
    if _REMOTE_ANY.search(low):
        return 2  # bare "Remote" with no country: assume Europe-eligible, verify later
    return _UNKNOWN


def priority_for(location_text, default=4):
    """Best priority across every location in the string, or DROP (None).

    - Any chunk that resolves to 1-4 wins, lowest number first. One German entry
      in a ten-country listing therefore never kills the row.
    - DROP only when every chunk is Germany or Ukraine.
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
    """True when a remote row names no Bulgarian location.

    Not a drop. GitLab states it will not hire where it has no entity or PEO and
    Bulgaria is not on its list; Grafana, Elastic and Veeam show no Bulgarian
    location either. Flag it so the note can say: перевірити, чи наймають у Болгарії.
    """
    text = location_text or ""
    if not _REMOTE_ANY.search(text) and not _REMOTE_EUROPE.search(text):
        return False
    return not any(_classify(c) == 1 for c in _chunks(text))


def explain(location_text):
    """Human-readable reason, for run.log."""
    p = priority_for(location_text)
    if p is DROP:
        return "drop: Germany or Ukraine only"
    return {
        1: "p1: Sofia / Bulgaria",
        2: "p2: EU, Warsaw or remote",
        3: "p3: non-EU temporary protection",
        4: "p4: work visa needed",
    }[p]
