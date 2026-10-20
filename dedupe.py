"""
dedupe.py - one duplicate check for Agent 1 (poll_jobs / job_filters) and the 08:49 tracker import.
Rule agreed with Mykola 13.10.2026: before a card is created, compare it with the tracker by
URL, by board job id, and by canonical company + similar role. Python 3.9, no dependencies.

Verdicts for a candidate posting:
  dup       - same URL, same board job id, or same company + same/similar role
              (same meaningful title words) on a card added in the last REPOST_DAYS days.
              -> do NOT create a card.
  possible  - same company + same role family, but the role differs, or the matching card
              is older than REPOST_DAYS. -> create the card, mark it "Можливий дубль: ...".
  new       - nothing similar.

CLI:
  python3 dedupe.py index data/tracker_export.json data/tracker_index.json
  python3 dedupe.py check out/import_latest.json data/tracker_export.json [out/import_checked.json]
      # every import item + verdict, why, match, match_id
  python3 dedupe.py selftest data/tracker_export.json                       # clusters inside the tracker
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

REPOST_DAYS = 60

# Legal forms and filler words dropped from company names.
CO_DROP = {"sp", "z", "o", "oo", "llc", "ltd", "limited", "inc", "eood", "ood", "ad", "gmbh", "sa", "ag",
           "bv", "plc", "srl", "sro", "as", "oy", "ab", "the", "group", "technologies", "technology",
           "systems", "software", "solutions", "company", "co", "corp", "corporation", "holding",
           "holdings", "international", "global", "recruiting", "bulgaria", "polska", "poland",
           "sofia", "ukraine", "europe", "payward", "io", "com", "dev", "app"}
# Same employer under different names. Keys and values are already normalised.
CO_ALIAS = {
    "pin up": "redcore", "pin up global": "redcore", "redcore": "redcore",
    "namecheap": "zone3000", "zone3000": "zone3000", "zone 3000": "zone3000",
    "epam": "epam", "epam systems": "epam",
    "yellow": "yellow", "checkbox": "checkbox",
    "softswiss": "softswiss", "soft swiss": "softswiss",
    "gr8": "gr8 tech", "gr8 tech": "gr8 tech",
    "gen tech": "genesis", "genesis": "genesis",
    "ness": "ness", "ness solution": "ness",
    "hedgeserv": "hedgeserv", "hcl": "hcltech", "hcltech": "hcltech", "hcl tech": "hcltech",
    "kraken": "kraken", "act digital": "act digital", "actdigital": "act digital",
}
WORD = re.compile(r"[0-9a-zа-яіїєґ]+", re.I)

FAMILY_RULES = [  # first match wins; order matters
    ("scrum", r"\b(scrum|agile coach|agile delivery|release train|rte)\b|скрам"),
    ("po", r"\bproduct owner\b|\btpo\b|\bpo\b"),
    ("product", r"\bproduct (manager|lead|director|management)|\bhead of product\b|\bcpo\b|продукт"),
    ("program", r"\b(program|programme) (manager|director|lead)\b|\bpgm\b"),
    ("delivery", r"\bdelivery (manager|director|lead|head)|\bhead of delivery\b|\bsdm\b|\bvp delivery\b"),
    ("project", r"\bproject (manager|lead|director)|\bpm\b|\btpm\b|\bproject delivery\b|проєкт|проект"),
    ("ops", r"\b(operations|operational|ops)\b"),
    ("ba", r"\b(business analyst|system analyst|ba)\b"),
]
ROLE_DROP = {
    # family words
    "product", "project", "program", "programme", "delivery", "scrum", "master", "owner", "manager",
    "management", "lead", "leader", "head", "director", "of", "pm", "po", "tpm", "pgm", "sdm", "tpo",
    # seniority / filler
    "senior", "sr", "middle", "mid", "strong", "junior", "jr", "principal", "staff", "chief", "expert",
    "team", "the", "and", "for", "with", "in", "on", "to", "a", "an", "at", "level", "role", "position",
    "m", "f", "d", "x", "w", "k", "it", "new", "our", "we", "are", "hiring",
    # place / work mode
    "repost", "freelance", "remote", "hybrid", "onsite", "office", "full", "time", "fulltime", "contract", "b2b", "freelance",
    "sofia", "bulgaria", "warsaw", "warszawa", "krakow", "poland", "kyiv", "ukraine", "lviv", "europe",
    "eu", "emea", "cee", "worldwide", "limassol", "cyprus", "bucharest", "romania", "uk", "us", "usa",
}


def norm_company(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    words = WORD.findall(s)
    kept = [w for w in words if w not in CO_DROP] or words
    key = " ".join(kept)
    return CO_ALIAS.get(key, CO_ALIAS.get(" ".join(words), key))


def family(role: str) -> str:
    r = (role or "").lower().replace("-", " ")
    for fam, rx in FAMILY_RULES:
        if re.search(rx, r):
            return fam
    return "other"


def role_core(role: str) -> frozenset:
    """Meaningful words of a role title. Words with digits are job ids, not words.
    Cyrillic words are dropped when the title also has Latin words: they are our own notes."""
    words = WORD.findall((role or "").lower())
    latin = any(re.match(r"[a-z]", w) for w in words)
    keep = set()
    for w in words:
        if w in ROLE_DROP or len(w) < 2 or any(ch.isdigit() for ch in w):
            continue
        if latin and not re.match(r"[a-z]", w):
            continue
        keep.add(w)
    return frozenset(keep)


def title_ids(role: str) -> frozenset:
    return frozenset(re.findall(r"\d{4,}", role or ""))


def norm_url(u: str) -> str:
    if not u:
        return ""
    try:
        p = urlsplit(u.strip().lower())
    except ValueError:
        return u.strip().lower()
    return (p.netloc.replace("www.", "") + p.path).rstrip("/")


def board_ids(u: str) -> frozenset:
    """Job ids that survive a re-post on the same board are rare, but ids are exact when equal."""
    return frozenset(re.findall(r"\d{5,}", norm_url(u)))


def _d(s: str):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m"):
        try:
            d = datetime.strptime(str(s)[:10], fmt).date()
            return d.replace(year=date.today().year) if fmt == "%d.%m" else d
        except (ValueError, TypeError):
            continue
    return None


def build_index(rows: list) -> list:
    out = []
    for r in rows:
        d = r.get("data", r)
        out.append({
            "id": r.get("id") or d.get("id"), "company": d.get("company", ""), "role": d.get("role", ""),
            "status": d.get("status", ""), "added": d.get("added", ""), "applied": d.get("applied", ""),
            "co": norm_company(d.get("company", "")), "fam": family(d.get("role", "")),
            "core": sorted(role_core(d.get("role", ""))), "url": norm_url(d.get("url", "")),
            "ids": sorted(board_ids(d.get("url", "")) | title_ids(d.get("role", ""))),
        })
    return out


def check(company: str, role: str, url: str, index: list, today: date = None) -> dict:
    today = today or date.today()
    u = norm_url(url)
    ids = board_ids(url) | title_ids(role)
    co, fam, core = norm_company(company), family(role), role_core(role)
    best = None
    for c in index:
        if u and u == c["url"]:
            return {"verdict": "dup", "why": "same url", "match": c}
        same_co = bool(co) and c["co"] == co
        if same_co and ids & set(c["ids"]):
            return {"verdict": "dup", "why": "same job id", "match": c}
        if not same_co or c["fam"] != fam:
            continue
        other = frozenset(c["core"])
        if core and other and not core & other:
            continue                      # same company, clearly different role
        if core == other:
            strong = True                 # identical meaningful words (or both generic)
        elif core and other and (core <= other or other <= core):
            strong = min(len(core), len(other)) >= 2 and len(core ^ other) <= 1
        else:
            strong = False                # one title generic, the other specific; or partial overlap
        if ids and c["ids"] and not ids & set(c["ids"]):
            strong = False                # two different job ids: may be a repost, may be a second opening
        added = _d(c.get("added")) or _d(c.get("applied"))
        fresh = added is not None and (today - added).days <= REPOST_DAYS
        verdict = "dup" if strong and fresh else "possible"
        why = f"same company + {fam}, " + ("same role" if strong else "similar role")
        if strong and not fresh:
            why += f", card older than {REPOST_DAYS} days"
        cand = {"verdict": verdict, "why": why, "match": c}
        if verdict == "dup":
            return cand
        if best is None:
            best = cand
    return best or {"verdict": "new", "why": "", "match": None}


def label(m: dict) -> str:
    return f"{m['company']} - {m['role']} ({m['status']}, {m['id']})"


def _load(path: str) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list) -> int:
    if len(argv) >= 3 and argv[0] == "index":
        idx = build_index(_load(argv[1]))
        Path(argv[2]).write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"index: {len(idx)} cards -> {argv[2]}")
        return 0
    if len(argv) >= 3 and argv[0] == "check":
        idx = build_index(_load(argv[2]))
        res = []
        for it in _load(argv[1]):
            if not it.get("company") or not it.get("role"):
                continue
            v = check(it.get("company", ""), it.get("role", ""), it.get("url", ""), idx)
            res.append(dict(it, verdict=v["verdict"], why=v["why"],
                            match=label(v["match"]) if v["match"] else "",
                            match_id=v["match"]["id"] if v["match"] else ""))
            if v["verdict"] != "dup":   # items in the same file are checked against each other too
                idx += build_index([{"id": "(this import)", "company": it.get("company", ""),
                                     "role": it.get("role", ""), "url": it.get("url", ""),
                                     "status": "new", "added": date.today().isoformat()}])
        out = json.dumps(res, ensure_ascii=False, indent=1)
        if len(argv) >= 4:
            Path(argv[3]).write_text(out, encoding="utf-8")
            n = {k: sum(r["verdict"] == k for r in res) for k in ("new", "possible", "dup")}
            print(f"checked {len(res)}: new {n['new']}, possible {n['possible']}, dup {n['dup']} -> {argv[3]}")
        else:
            print(out)
        return 0
    if len(argv) >= 2 and argv[0] == "selftest":
        idx = build_index(_load(argv[1]))
        n = 0
        for i, a in enumerate(idx):
            v = check(a["company"], a["role"], "", idx[:i])
            if v["verdict"] != "new":
                n += 1
                print(f"{v['verdict']:8s} {label(a)}  ==  {label(v['match'])}  [{v['why']}]")
        print(f"{n} of {len(idx)} cards look like a duplicate of an earlier card")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
