"""
job_filters.py - second-pass filter for Agent 1 (called from poll_jobs.py).

Every posting that passed the title / location / age filters gets one verdict:
  main        -> goes to the daily email and out/latest.md; carries p["priority"] 1-3
  drop        -> ignored (reason is counted in run.log)
(The "relocation" verdict and data/relocation_watch.json were retired on 25.10.2026.)

Rules agreed with Mykola on 11.10.2026, changed on 25.10.2026:
  1. A language in the title (German speaking, with French, ...) -> drop. Unchanged: working-level
     Polish stays a blocker. Language and location are separate axes.
  2. Ukraine only, even if marked "Remote" -> drop. Poland is no longer dropped on location.
  3. Location is a priority, not a waiting list (priorities.py, on top of location_rules.py):
     1 = Sofia on-site/hybrid, or fully remote; 2 = relocation within Europe or a country that gives
     Ukrainians temporary protection; 3 = needs a work visa or protection does not apply.
     Germany-only and Ukraine-only are dropped. A multi-country string keeps its best priority.
  4. Already in the tracker -> drop as duplicate. 13.10: dedupe.py (URL, job id, canonical company +
     same role family + same meaningful title words, card younger than 60 days).
Python 3.9 compatible, no extra dependencies.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import dedupe
import location_rules
import priorities

LANG_IN_TITLE = re.compile(
    r"\b(german|deutsch|french|fran[cç]ais|dutch|polish|italian|spanish|portuguese|czech|slovak|"
    r"hungarian|romanian|swedish|norwegian|danish|finnish|japanese|korean|chinese|mandarin|hebrew|"
    r"turkish|greek|arabic)\b", re.I)
BROAD = re.compile(r"\b(europe|european union|emea|worldwide|anywhere|global|eu)\b", re.I)
REMOTE = re.compile(r"\b(remote|anywhere|worldwide|home[- ]based|work from home)\b", re.I)
HOME = re.compile(r"\b(bulgaria|sofia)\b", re.I)
COUNTRIES = [
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic", "czechia", "denmark",
    "estonia", "finland", "france", "germany", "greece", "hungary", "ireland", "italy", "latvia",
    "lithuania", "luxembourg", "malta", "netherlands", "poland", "portugal", "romania", "slovakia",
    "slovenia", "spain", "sweden", "ukraine", "united kingdom", "switzerland", "norway", "serbia",
    "israel", "georgia", "armenia", "turkey", "united arab emirates",
]
NON_EU = re.compile(r"\b(us|usa|u\.s\.|united states|canada|ca|amer|americas|latam|apac|australia|india|"
                    r"singapore|philippines|brazil|mexico)\b", re.I)
JUNIOR_OR_OFFSCOPE = re.compile(r"\b(intern|internship|junior|associate|graduate|grad|trainee|marketing|coordinator|"
                                r"course|training program|learning|returns|servicenow|itsm|trading|derivatives)\b", re.I)
LOW_PAY_BUCKET = re.compile(r"·\s*\$\s*$")  # Djinni "$" = below average for the role
CITY_TO_COUNTRY = {
    "vilnius": "lithuania", "kaunas": "lithuania", "warsaw": "poland", "warszawa": "poland",
    "krakow": "poland", "kraków": "poland", "wroclaw": "poland", "wrocław": "poland", "gdansk": "poland",
    "gdańsk": "poland", "poznan": "poland", "poznań": "poland", "lodz": "poland", "łódź": "poland",
    "katowice": "poland", "szczecin": "poland", "amsterdam": "netherlands", "rotterdam": "netherlands",
    "berlin": "germany", "munich": "germany", "münchen": "germany", "hamburg": "germany",
    "tallinn": "estonia", "riga": "latvia", "lisbon": "portugal", "porto": "portugal", "madrid": "spain",
    "barcelona": "spain", "prague": "czechia", "praha": "czechia", "brno": "czechia",
    "bucharest": "romania", "cluj": "romania", "limassol": "cyprus", "nicosia": "cyprus",
    "london": "united kingdom", "kyiv": "ukraine", "lviv": "ukraine", "kharkiv": "ukraine",
    "dnipro": "ukraine", "belgrade": "serbia", "tbilisi": "georgia", "yerevan": "armenia",
    "sliema": "malta", "valletta": "malta", "athens": "greece", "budapest": "hungary",
    "vienna": "austria", "dublin": "ireland", "paris": "france", "milan": "italy", "rome": "italy",
    "helsinki": "finland", "stockholm": "sweden", "copenhagen": "denmark", "zurich": "switzerland",
    "zürich": "switzerland", "brussels": "belgium", "tel aviv": "israel", "dubai": "united arab emirates",
}
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
    """Company exclusions from data/company_rules.json that apply everywhere (not the agency ones)."""
    try:
        rules = json.loads(Path("data/company_rules.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return [k.lower() for k, why in rules.get("exclude", {}).items() if not str(why).lower().startswith("agency")]


HARD_EXCLUDES = _hard_excludes()


def classify(p: dict, idx: dict):
    title, loc = p.get("title", ""), (p.get("location") or "")
    company = " ".join([str(p.get("hiring_entity", "")), str(p.get("source_board", ""))]).lower()
    for ex in HARD_EXCLUDES:
        if re.search(r"\b" + re.escape(ex) + r"\b", company):
            return "drop", f"excluded company ({ex})"
    low = loc.lower()
    if LANG_IN_TITLE.search(title):
        return "drop", "language in title"
    if JUNIOR_OR_OFFSCOPE.search(title):
        return "drop", "junior or off-scope title"
    if LOW_PAY_BUCKET.search(loc):
        return "drop", "Djinni pay bucket $ (below average)"
    if in_tracker(p, idx):
        return "drop", "already in tracker"
    # 25.10: location is a priority, not a relocation waiting list. 26.10: three levels (priorities.py).
    # Only Germany-only and Ukraine-only are location drops. "Armenia only" and "non-EU region"
    # no longer drop: priority_for() ranks them 4.
    prio = priorities.priority3(loc)
    if prio is None:
        return "drop", location_rules.explain(loc)
    if prio == 3 and not priorities.SHOW_P3:
        return "drop", "P3 hidden (needs a visa; priorities.SHOW_P3)"
    p["priority"] = prio
    if location_rules.entity_risk(loc):
        p["entity_risk"] = True
    found = {c for c in COUNTRIES if c in low}
    found |= {country for city, country in CITY_TO_COUNTRY.items() if city in low}
    if found and found <= {"ukraine"}:  # Poland removed from this rule on 25.10; language rules are separate
        return "drop", "Ukraine only"
    return "main", ""


def update_relocation_watch(rows: list, json_path: Path, md_path: Path) -> int:
    """Store relocation roles quietly. Returns how many were new."""
    try:
        watch = json.loads(json_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        watch = {}
    now = datetime.now(timezone.utc).date().isoformat()
    new = 0
    for p in rows:
        key = p.get("apply") or f"{p.get('source_board')}|{p.get('title')}|{p.get('location')}"
        rec = watch.get(key)
        if rec is None:
            new += 1
            watch[key] = {"company": p.get("source_board"), "title": p.get("title"),
                          "location": p.get("location"), "posted": p.get("posted_display"),
                          "first_seen": now, "last_seen": now, "times_seen": 1}
        else:
            rec["last_seen"], rec["times_seen"] = now, rec.get("times_seen", 1) + 1
    json_path.write_text(json.dumps(watch, ensure_ascii=False, indent=1), encoding="utf-8")

    live = {k: v for k, v in watch.items() if v["last_seen"] == now}
    by_company = Counter(v["company"] for v in live.values())
    lines = [f"# Переїзд - список очікування ({now})", "",
             "Не потрапляє в лист і в трекер. Коли знадобиться - бери звідси найкращі.", "",
             f"Живих зараз: {len(live)}. Усього бачили: {len(watch)}.", "",
             "## Хто наймає з переїздом (живі вакансії)", ""]
    lines += [f"- {c}: {n}" for c, n in by_company.most_common()]
    lines += ["", "## Живі вакансії, найновіші першими", "",
              "| Компанія | Роль | Де | Вперше | Посилання |", "|---|---|---|---|---|"]
    for k, v in sorted(live.items(), key=lambda kv: kv[1]["first_seen"], reverse=True):
        link = f"[Apply]({k})" if str(k).startswith("http") else "-"
        cells = [str(x or "").replace("|", "/") for x in (v["company"], v["title"], v["location"])]
        lines.append(f"| {cells[0]} | {cells[1]} | {cells[2]} | {v['first_seen']} | {link} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return new
