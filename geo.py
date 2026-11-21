"""
geo.py - the geography catalogue (geo/places.json) as Python helpers. Standard library only.

The catalogue knows countries (official names and aliases, main cities, the regions a country belongs to),
named groups of countries ("eu", "protected_non_eu"), marker groups (places that scope a "remote" job to a
region outside your reach) and language names. It contains no personal preferences: which country is home,
which are relocation zones and which are excluded comes from the user's profile (profile.py).
"""
from __future__ import annotations

import json
from pathlib import Path

_PATH = Path(__file__).with_name("geo") / "places.json"
_CAT = None


def catalogue() -> dict:
    global _CAT
    if _CAT is None:
        _CAT = json.loads(_PATH.read_text(encoding="utf-8"))
    return _CAT


def country_keys() -> set:
    return set(catalogue()["countries"])


def group_names() -> set:
    return set(catalogue()["groups"])


def names_of(key: str) -> set:
    """Official names and aliases of one country (no cities)."""
    c = catalogue()["countries"][key]
    return set(c["names"])


def tokens_of(key: str) -> set:
    """Every word or phrase that points at this country: names, aliases and main cities."""
    c = catalogue()["countries"][key]
    return set(c["names"]) | set(c["cities"])


def regions_of(key: str) -> set:
    return set(catalogue()["countries"][key]["regions"])


def expand_countries(spec) -> set:
    """['@eu', 'norway'] -> set of country keys. A leading @ names a group. Unknown names raise KeyError."""
    out = set()
    cat = catalogue()
    for item in spec or []:
        item = str(item).strip().lower()
        if item.startswith("@"):
            if item[1:] not in cat["groups"]:
                raise KeyError(item)
            out |= set(cat["groups"][item[1:]])
        else:
            if item not in cat["countries"]:
                raise KeyError(item)
            out.add(item)
    return out


def tokens_for(keys) -> set:
    out = set()
    for k in keys:
        out |= tokens_of(k)
    return out


def all_tokens() -> set:
    return tokens_for(country_keys())


def marker_tokens(name: str) -> set:
    return set(catalogue()["marker_groups"][name])


def language_tokens(key: str) -> list:
    return catalogue()["languages"][key]


def language_keys() -> set:
    return set(catalogue()["languages"])


def world_words() -> list:
    return list(catalogue()["world_words"])


def local_names_of(key: str) -> list:
    """Names of the country as they appear INSIDE job ads written in other languages (matched without word boundaries)."""
    return catalogue()["countries"][key].get("local", [])


def all_country_names() -> list:
    """Every country name and alias, longest first (for ad-text patterns)."""
    names = set()
    for k in country_keys():
        names |= names_of(k)
    return sorted(names, key=len, reverse=True)


def country_in(text: str):
    """Which country does this short text name? Longest name wins. Returns a country key or None."""
    import re
    low = (text or "").lower()
    best = None
    for k in country_keys():
        for n in names_of(k):
            if re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", low) and (best is None or len(n) > best[0]):
                best = (len(n), k)
    return best[1] if best else None


def language_in(text: str):
    """Which language does this short text name? Returns a language key or None."""
    import re
    low = (text or "").lower()
    for key, toks in catalogue()["languages"].items():
        for t in toks:
            if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low):
                return key
    return None
