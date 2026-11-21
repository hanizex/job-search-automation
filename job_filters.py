"""
job_filters.py - second-pass filter (called from poll_jobs.py).

Every posting that passed the title / location / age filters gets one verdict:
  main        -> goes to the daily email and out/latest.md; carries p["priority"] 1-3
  drop        -> ignored (the reason is counted in run.log)

The rules come from the search profile (search_profile.py):
  1. A language in the title that you do not speak (roles / languages.spoken) -> drop.
  2. Words that make a title not a fit (roles.exclude_title_words) -> drop.
  3. Companies you excluded (companies.exclude, data/company_rules.json) -> drop.
  4. Location is a priority, not a waiting list (priorities.py, on top of location_rules.py):
     1 = home, or fully remote; 2 = a relocation zone; 3 = needs a visa or is in none of your zones.
     Excluded places are dropped. A multi-country string keeps its best priority.
  5. Already in the tracker -> drop as duplicate (dedupe.py: URL, job id, canonical company +
     same role family + same meaningful title words, card younger than 60 days).
Python 3.9 compatible, no extra dependencies.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import dedupe
import location_rules
import priorities
import search_profile as _profile

LOW_PAY_BUCKET = re.compile(r"·\s*\$\s*$")  # Djinni "$" = below average for the role
SUFFIX = {"sp", "z", "o", "oo", "llc", "ltd", "inc", "eood", "ood", "gmbh", "sa", "ag", "bv", "plc",
          "group", "technologies", "bulgaria", "polska", "poland", "sofia", "the", "payward"}


def _norm_company(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    words = [w for w in re.split(r"[^0-9a-z]+", s) if w]
    return " ".join([w for w in words if w not in SUFFIX] or words)


def _title_tokens(s: str) -> set:
    return {w for w in re.split(r"[^0-9a-z]+", (s or "").lower()) if len(w) >= 3}


def _ids(url: str) -> set:
    return set(re.findall(r"\d{6,}", url or ""))


def load_tracker_index(path: Path) -> list:
    """13.10: one duplicate check for code and the 08:49 import - see dedupe.py."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return dedupe.build_index(rows)


def in_tracker(p: dict, idx: list) -> bool:
    """Drop only clear duplicates. 'possible' duplicates go on; the 08:49 import flags them."""
    company = p.get("hiring_entity") if p.get("hiring_entity") not in (None, "", "UNKNOWN") else p.get("source_board", "")
    url = p.get("apply") if p.get("apply") not in (None, "UNKNOWN") else ""
    names = [company] + [n for n in str(p.get("source_board", "")).split(" / ") if n and n != company]
    for name in names:
        if dedupe.check(name, p.get("title", ""), url, idx)["verdict"] == "dup":
            return True
    return False


def _hard_excludes() -> list:
    """Company exclusions that apply everywhere: the profile's companies.exclude plus data/company_rules.json
    (entries whose reason starts with "agency" are not hard exclusions)."""
    out = set(_profile.compiled().exclude_companies)
    try:
        rules = json.loads(Path("data/company_rules.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        rules = {}
    out |= {k.lower() for k, why in rules.get("exclude", {}).items() if not str(why).lower().startswith("agency")}
    return sorted(out)


def classify(p: dict, idx: dict):
    title, loc = p.get("title", ""), (p.get("location") or "")
    company = " ".join([str(p.get("hiring_entity", "")), str(p.get("source_board", ""))]).lower()
    cfg = _profile.compiled()
    for ex in _hard_excludes():
        if re.search(r"\b" + re.escape(ex) + r"\b", company):
            return "drop", f"excluded company ({ex})"
    low = loc.lower()
    if cfg.lang_re and cfg.lang_re.search(title):
        return "drop", "language in title"
    if cfg.off_scope_re and cfg.off_scope_re.search(title):
        return "drop", "junior or off-scope title"
    if LOW_PAY_BUCKET.search(loc):
        return "drop", "Djinni pay bucket $ (below average)"
    if in_tracker(p, idx):
        return "drop", "already in tracker"
    # location is a priority, not a relocation waiting list. 26.10: three levels (priorities.py).
    # Only Germany-only and Ukraine-only are location drops. "Armenia only" and "non-EU region"
    # no longer drop: priority_for() ranks them 4.
    prio = priorities.priority3(loc)
    if prio is None:
        return "drop", location_rules.explain(loc)
    if prio == 3 and not (priorities.SHOW_P3 or cfg.show_p3):
        return "drop", "P3 hidden (needs a visa; priorities.SHOW_P3)"
    p["priority"] = prio
    if location_rules.entity_risk(loc):
        p["entity_risk"] = True
    # Ukraine-only is dropped by priorities.priority3 above. The older text rule ("every named country is Ukraine")
    # is gone : it also fired on "Ukraine; Remote, anywhere", where priority3 correctly says P1
    # (a remote entry with no country), so a worldwide remote job was lost.
    return "main", ""
