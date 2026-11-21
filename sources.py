"""
sources.py - which job-board searches fit which roles (catalog/sources.json). Standard library only.

DOU accepts any search term as a feed "category". Djinni accepts only its own keywords; an unknown keyword
silently returns the unfiltered latest jobs, so keywords are validated against the catalogue.
suggest(titles) turns the profile's job titles into DOU terms and Djinni keywords, so nobody has to pick them by hand.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PATH = Path(__file__).with_name("catalog") / "sources.json"
_CAT = None


def catalogue() -> dict:
    global _CAT
    if _CAT is None:
        _CAT = json.loads(_PATH.read_text(encoding="utf-8"))
    return _CAT


def board_names() -> list:
    return list(catalogue()["boards"])


def djinni_keywords() -> list:
    return list(catalogue()["djinni_keywords"])


def _has(title: str, token: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", title) is not None


def suggest(titles) -> dict:
    """-> {"dou": [...], "djinni": [...], "unmatched": [titles with no catalogue match]}.
    A title with no match still becomes a DOU search term (DOU takes any term); Djinni needs a known keyword, so it is skipped."""
    dou, djinni, unmatched = [], [], []
    for raw in titles:
        title = str(raw).lower()
        hit = False
        for rule in catalogue()["role_map"]:
            if any(_has(title, tok) for tok in rule["match"]):
                hit = True
                for t in rule["dou"]:
                    if t not in dou:
                        dou.append(t)
                for k in rule["djinni"]:
                    if k not in djinni:
                        djinni.append(k)
        if not hit:
            unmatched.append(raw)
            if re.search(r"[a-z]", title) and title not in [d.lower() for d in dou]:
                dou.append(raw)
    return {"dou": dou, "djinni": djinni, "unmatched": unmatched}
