"""
Collapse multi-country duplicates inside a single import.

New file, 25.10.2026. Standard library only, Python 3.9+.

Large employers publish one requisition once per country, one row per country.
Elastic's "Senior Product Manager (XDR)" appears six times: Spain, Ireland,
Portugal, Poland, Greece, Switzerland. Without this step that is six tracker
cards for one job.

dedupe.py already compares an incoming row against the tracker. This runs one
step earlier and squashes the import against itself.

It reuses dedupe.py's normalisers when they are importable, so the two stay in
agreement, and falls back to a local copy when run standalone.
"""

import re
from collections import OrderedDict

try:  # keep one definition of "same company" across both files
    from dedupe import norm_company as _norm_company  # type: ignore
except Exception:  # pragma: no cover - exercised only without dedupe.py
    _LEGAL = {
        "ltd", "llc", "inc", "gmbh", "bv", "b.v.", "ab", "as", "oy", "sa", "s.a.",
        "plc", "group", "software", "systems", "technologies", "labs", "co",
        "corp", "holding", "sp", "zoo", "z.o.o.", "the",
    }

    def _norm_company(name):
        words = re.findall(r"[a-z0-9]+", (name or "").lower())
        kept = [w for w in words if w not in _LEGAL]
        return " ".join(kept or words)

# Deliberately NOT dedupe.role_core: it returns a frozenset and drops generic
# words (product, program, project, manager, delivery, senior), so "Product
# Manager" and "Program Manager" at one company would share a key and be merged
# into one card when the URL carries no requisition id. This module keeps its
# own role key and only ignores formatting noise (work mode, m/f/d, stop words).
# Seniority words (senior, lead, staff, principal, head) are NOT noise: they
# name different vacancies, and different vacancies must never share a card.
_NOISE = {
    "of", "the", "and", "a", "an", "for", "to", "in", "at",
    "remote", "hybrid", "onsite", "on", "site", "office", "full", "time",
    "part", "contract", "permanent", "m", "f", "d", "x", "all", "genders",
}


def _role_core(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    kept = [w for w in words if w not in _NOISE and not any(ch.isdigit() for ch in w)]
    return " ".join(sorted(set(kept)))


# Requisition ids in the wild: R026632, JR2017192, REF082383W, _r20546, ID89740.
# The trailing letter in REF082383W means we must not demand a word boundary
# straight after the digits, or two different reqs collapse into one card.
_REQ_ID = re.compile(r"\b(?:req|jr|r|id|ref)[-_ ]?(\d{4,}[a-z]?)\b", re.I)


def _job_id(row):
    """A requisition id, when the URL or title carries one."""
    for field in (row.get("url") or "", row.get("role") or ""):
        m = _REQ_ID.search(field)
        if m:
            return m.group(1)
    return None


def _key(row):
    company = _norm_company(row.get("company"))
    jid = _job_id(row)
    if jid:
        return (company, "id:" + jid)
    return (company, "role:" + _role_core(row.get("role")))


def collapse(rows, priority_of=None):
    """Squash rows that are the same job published in several countries.

    rows: list of dicts in the poll_jobs shape.
    priority_of: optional callable(location_text) -> int or None, normally
                 location_rules.priority_for. When given, the surviving row
                 keeps the best priority and the URL that earns it.

    Returns a new list, original order of first appearance preserved. Each
    surviving row gains:
        location  all locations, joined with "; "
        priority  the best priority among them (only when priority_of is given)
        variants  how many rows were merged into it (absent when 1)
    """
    groups = OrderedDict()
    for row in rows:
        groups.setdefault(_key(row), []).append(row)

    out = []
    for members in groups.values():
        if len(members) == 1:
            row = dict(members[0])
            if priority_of is not None:
                row["priority"] = priority_of(row.get("location"))
            out.append(row)
            continue

        best = members[0]
        best_p = None
        locations = []
        for member in members:
            loc = (member.get("location") or "").strip()
            if loc:
                locations.append(loc)
            if priority_of is not None:
                p = priority_of(loc)
                if p is not None and (best_p is None or p < best_p):
                    best_p, best = p, member

        merged = dict(best)
        seen, joined = set(), []
        for loc in locations:
            for part in re.split(r"\s*;\s*", loc):
                part = part.strip()
                if part and part.lower() not in seen:
                    seen.add(part.lower())
                    joined.append(part)
        merged["location"] = "; ".join(joined)
        merged["variants"] = len(members)
        if priority_of is not None:
            merged["priority"] = best_p
        # keep the earliest known posting date
        dates = sorted(d for d in (m.get("posted") or "" for m in members) if d)
        if dates:
            merged["posted"] = dates[0]
        out.append(merged)

    return out


def report(before, after):
    """One line for run.log."""
    saved = len(before) - len(after)
    if saved <= 0:
        return f"collapse: {len(before)} rows, no multi-country duplicates"
    merged = [r for r in after if r.get("variants", 1) > 1]
    worst = max(merged, key=lambda r: r["variants"])
    return (f"collapse: {len(before)} -> {len(after)} rows "
            f"({saved} duplicate country rows merged; worst: "
            f"{worst.get('company')} {worst.get('role')} x{worst['variants']})")
