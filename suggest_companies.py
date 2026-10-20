#!/usr/bin/env python3
"""
suggest_companies.py - keeps Agent 1's company list (data/companies.json) alive.

It answers two questions every time it runs:
  1. Which companies from the tracker are worth scanning directly?
  2. Which companies already in the list bring nothing and can go?

    python3 suggest_companies.py              # report only (probes ATS over the network)
    python3 suggest_companies.py --no-probe   # report only, no network at all
    python3 suggest_companies.py --apply      # report + update data/companies.json

Inputs (all local files):
  data/tracker_export.json  - export of the "Мої вакансії" tracker (company, role, status, url, added)
  data/companies.json       - Agent 1's scan list
  data/company_rules.json   - weights, thresholds, exclusions, aliases (edit by hand)
  out/jobs_*.md, data/run.log - what Agent 1 actually found, to measure each company's yield
Output:
  out/company_suggestions.md - human-readable report (Ukrainian)
  data/ats_cache.json        - remembered ATS lookups, so the network is hit rarely

Python 3.9 compatible. Only dependency: requests (already used by poll_jobs.py).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "out"
TODAY = dt.date.today()

SUFFIX_WORDS = {
    "sp", "z", "o", "oo", "llc", "ltd", "limited", "inc", "eood", "ood", "ead", "gmbh",
    "sa", "ag", "bv", "plc", "group", "technologies", "bulgaria", "polska", "poland",
    "sofia", "ukraine", "company", "corp", "corporation", "the",
}
# Hosts that are job boards, not a company's own careers page.
JOB_BOARDS = {
    "justjoin.it", "jobs.dou.ua", "djinni.co", "mymgr.app", "dev.bg", "linkedin.com",
    "jobs.bg", "nofluffjobs.com", "pracuj.pl", "bulldogjob.pl", "rocketjobs.pl",
    "jooble.org", "indeed.com", "glassdoor.com", "wellfound.com", "remoteok.com",
    "workingnomads.com", "weworkremotely.com", "jobico.io", "thejob.tech", "work.ua",
    "robota.ua", "theprotocol.it", "solid.jobs", "skillie.ai",
}
UNNAMED = re.compile(r"^\(|unnamed|не\s*назван|не\s*вказан|не\s*розкрит|невідом|реф\s*від|confidential|конфіденц|"
                     r"^client|^klient|^клієнт|^\?|^-$|^n/?a$", re.I)

# Known ATS URL shapes -> (ats, endpoint template). Endpoint formats match ats_fetch.py.
ATS_URL_RULES = [
    (r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([^/?#&]+)", "Greenhouse",
     "https://boards-api.greenhouse.io/v1/boards/{}/jobs"),
    (r"jobs(?:\.eu)?\.lever\.co/([^/?#]+)", "Lever", "https://api.lever.co/v0/postings/{}?mode=json"),
    (r"jobs\.ashbyhq\.com/([^/?#]+)", "Ashby", "https://api.ashbyhq.com/posting-api/job-board/{}"),
    (r"(?:jobs|careers)\.smartrecruiters\.com/([^/?#]+)", "SmartRecruiters",
     "https://api.smartrecruiters.com/v1/companies/{}/postings"),
    (r"apply\.workable\.com/([^/?#]+)", "Workable", "https://apply.workable.com/api/v1/widget/accounts/{}"),
    (r"https?://([^./]+)\.recruitee\.com", "Recruitee", "https://{}.recruitee.com/api/offers/"),
    (r"https?://([^./]+)\.breezy\.hr", "Breezy HR", "https://{}.breezy.hr/json"),
    (r"https?://([^./]+)\.teamtailor\.com", "Teamtailor", "https://{}.teamtailor.com/jobs"),
    (r"https?://([^./]+)\.jobs\.personio\.(?:de|com)", "Personio", "https://{}.jobs.personio.de/xml"),
]
WORKDAY_RE = re.compile(r"https?://([^./]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def fetchable_ats() -> set:
    try:
        import ats_fetch  # noqa: WPS433 - optional, needs requests
        return set(ats_fetch.FETCHABLE_ATS)
    except Exception:
        return {"Greenhouse", "Lever", "Ashby", "SmartRecruiters", "Workday", "Recruitee",
                "Breezy HR", "Workable", "Amazon (proprietary JSON API)"}


def norm(name: str, aliases: dict) -> str:
    raw = (name or "").strip().lower()
    if raw in aliases:
        raw = aliases[raw].lower()
    s = re.sub(r"\([^)]*\)", " ", raw)
    words = [w for w in re.split(r"[^0-9a-zа-яіїєґ]+", s) if w]
    kept = [w for w in words if w not in SUFFIX_WORDS] or words
    key = " ".join(kept)
    return aliases.get(key, key).lower()


def host_of(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def ats_from_url(url: str):
    """Return (ats, endpoint, note) if the URL itself reveals the company's ATS or own site."""
    if not url or not url.startswith("http"):
        return None
    for pattern, ats, tpl in ATS_URL_RULES:
        m = re.search(pattern, url)
        if m:
            return ats, tpl.format(m.group(1)), f"from tracker URL {url}"
    m = WORKDAY_RE.search(url)
    if m:
        tenant, pod, site = m.groups()
        return ("Workday", f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                f"from tracker URL {url}")
    h = host_of(url)
    if h and not any(h == b or h.endswith("." + b) for b in JOB_BOARDS):
        return "Custom site", f"https://{urlparse(url).netloc}", f"own careers site seen in tracker: {url}"
    return None


def yield_from_agent(aliases: dict, window_days: int):
    """Count matching postings per company in Agent 1 output files within the window."""
    since = TODAY - dt.timedelta(days=window_days)
    counts, last = Counter(), {}
    for f in sorted(OUT.glob("jobs_*.md")):
        m = re.search(r"jobs_(\d{4}-\d{2}-\d{2})\.md$", f.name)
        if not m:
            continue
        day = dt.date.fromisoformat(m.group(1))
        if day < since:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| ") or line.startswith("| Source Board") or line.startswith("|---"):
                continue
            board = line.split("|")[1].strip()
            for part in board.split(" / "):
                k = norm(part, aliases)
                counts[k] += 1
                last[k] = max(last.get(k, day), day)
    run_days = set()
    log = DATA / "run.log"
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\[(\d{4}-\d{2}-\d{2})T.*Run started", line)
            if m and dt.date.fromisoformat(m.group(1)) >= since:
                run_days.add(m.group(1))
    return counts, last, len(run_days)


def score_tracker(rows: list, rules: dict):
    aliases = {k.lower(): v for k, v in rules.get("aliases", {}).items()}
    w = rules["weights"]
    recent_cut = TODAY - dt.timedelta(days=rules["recent_days"])
    comp = defaultdict(lambda: {"names": Counter(), "status": Counter(), "roles": set(),
                                "urls": [], "recent": False, "score": 0})
    for r in rows:
        name = (r.get("company") or "").strip()
        if not name or UNNAMED.search(name) or (r.get("id") or "").startswith("old-"):
            continue
        k = norm(name, aliases)
        if not k:
            continue
        c = comp[k]
        c["names"][name] += 1
        st = r.get("status") or "todo"
        c["status"][st] += 1
        c["roles"].add((r.get("role") or "").strip().lower())
        if r.get("url"):
            c["urls"].append(r["url"])
        try:
            if r.get("added") and dt.date.fromisoformat(r["added"][:10]) >= recent_cut:
                c["recent"] = True
        except ValueError:
            pass
    for k, c in comp.items():
        s = sum(w.get(st, 0) * n for st, n in c["status"].items())
        extra = min(max(len(c["roles"]) - 1, 0), rules["extra_role_bonus_cap"])
        s += extra * rules["extra_role_bonus"]
        if c["recent"]:
            s += rules["recent_bonus"]
        c["score"] = s
        c["display"] = c["names"].most_common(1)[0][0]
    return comp, aliases


GENERIC_TOKENS = {"software", "group", "systems", "solutions", "tech", "labs", "digital", "global", "it"}


def slug_is_full_name(notes: str, name: str) -> bool:
    """True when the probe matched the whole company name, not just its first word."""
    m = re.search(r"via slug '([^']+)'", notes or "")
    if not m:
        return True
    slug = m.group(1).lower()
    words = re.findall(r"[A-Za-z0-9]+", re.sub(r"\([^)]*\)", " ", name))
    base = [w.lower() for w in words if w.lower() not in SUFFIX_WORDS] or [w.lower() for w in words]
    return len(base) <= 1 or slug in ("".join(base), "-".join(base))


def verify_greenhouse(endpoint: str, name: str, aliases: dict):
    """Ask Greenhouse whose board this is. Returns (True/False/None, board_name)."""
    m = re.search(r"https://(boards-api(?:\.eu)?\.greenhouse\.io)/v1/boards/([^/]+)/jobs", endpoint or "")
    if not m:
        return None, ""
    try:
        import requests
        r = requests.get(f"https://{m.group(1)}/v1/boards/{m.group(2)}", timeout=10,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; JobSearchDiscovery/1.0)"})
        board = (r.json() or {}).get("name", "") if r.status_code == 200 else ""
    except Exception:
        return None, ""
    if not board:
        return None, ""
    a = set(norm(board, aliases).split()) - GENERIC_TOKENS
    b = set(norm(name, aliases).split()) - GENERIC_TOKENS
    return bool(a & b) or norm(board, aliases) == norm(name, aliases), board


def check_endpoint(c: dict, aliases: dict, allow_network: bool):
    """Downgrade a fresh OK match to CHECK / MANUAL when it may belong to another company."""
    if c.get("scan_status") != "OK":
        return
    if c.get("ats") == "Greenhouse":
        ok, board = verify_greenhouse(c["endpoint"], c["display"], aliases) if allow_network else (None, "")
        if ok is True:
            c["notes"] = (c.get("notes", "") + f" Verified: Greenhouse board name '{board}'.").strip()
            c["verified_on"] = TODAY.isoformat()
        elif ok is False:
            c["scan_status"], c["action"] = "MANUAL", f"Greenhouse-борд належить іншій компанії ('{board}')"
            c["notes"] = (c.get("notes", "") + f" REJECTED: board name is '{board}'.").strip()
        else:
            c["scan_status"], c["action"] = "CHECK", "перевір вручну: назву борду не підтверджено"
    elif not slug_is_full_name(c.get("notes", ""), c["display"]):
        c["scan_status"], c["action"] = "CHECK", "перевір вручну: збіг лише за першим словом назви"


def why(c: dict) -> str:
    ua = {"interview": "співбесіда", "talk": "розмова", "offer": "оффер", "applied": "подано",
          "rejected": "відмова", "todo": "у черзі", "closed": "закрита", "skip": "пропущено"}
    parts = [f"{ua.get(st, st)} {n}" for st, n in c["status"].most_common()]
    parts.append(f"ролей {len(c['roles'])}")
    if c["recent"]:
        parts.append("свіжа")
    return ", ".join(parts)


def probe(name: str, cache: dict, allow_network: bool):
    key = name.lower()
    hit = cache.get(key)
    if hit:
        age = (TODAY - dt.date.fromisoformat(hit["checked"])).days
        if hit["status"] == "OK" or age < 30:
            return hit, False
    if not allow_network:
        return None, False
    try:
        import discover_ats
        res = discover_ats.discover_generic(name)
    except Exception as e:  # network down, missing requests, etc.
        return {"ats": "Unknown", "endpoint": "", "status": "ERROR", "notes": repr(e),
                "checked": TODAY.isoformat()}, True
    res = {k: res.get(k, "") for k in ("ats", "endpoint", "status", "notes")}
    res["checked"] = TODAY.isoformat()
    cache[key] = res
    return res, True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes to data/companies.json")
    ap.add_argument("--no-probe", action="store_true", help="never touch the network")
    ap.add_argument("--max-probe", type=int, default=25, help="max new ATS lookups per run")
    args = ap.parse_args()

    rules = load_json(DATA / "company_rules.json", None)
    if rules is None:
        raise SystemExit("data/company_rules.json is missing")
    rows = load_json(DATA / "tracker_export.json", [])
    companies = load_json(DATA / "companies.json", [])
    cache = load_json(DATA / "ats_cache.json", {})
    can_fetch = fetchable_ats()
    excl = {k.lower(): v for k, v in rules.get("exclude", {}).items()}

    comp, aliases = score_tracker(rows, rules)
    window = rules["auto_remove_after_days"]
    agent_counts, agent_last, run_days = yield_from_agent(aliases, window)

    existing = {}
    for e in companies:
        existing[norm(e["name"], aliases)] = e

    def excluded(k: str):
        for ex, reason in excl.items():
            if ex == k or k.startswith(ex + " ") or (" " + ex) in (" " + k):
                return reason
        return None

    add, watch, blocked, already = [], [], [], []
    for k, c in sorted(comp.items(), key=lambda kv: -kv[1]["score"]):
        reason = excluded(k)
        if reason:
            blocked.append((c, reason))
            continue
        if k in existing:
            already.append((c, existing[k]))
            continue
        if c["score"] >= rules["thresholds"]["add"]:
            add.append(c)
        elif c["score"] >= rules["thresholds"]["watch"]:
            watch.append(c)

    # Work out an endpoint for every ADD candidate.
    probes_left = args.max_probe
    for c in add:
        hint = None
        for u in c["urls"]:
            hint = ats_from_url(u)
            if hint and hint[0] != "Custom site":
                break
        if hint and hint[0] != "Custom site":
            ats, endpoint, note = hint
            c["ats"], c["endpoint"] = ats, endpoint
            c["scan_status"] = "OK" if ats in can_fetch else "MANUAL"
            c["action"] = ("додано в сканування" if c["scan_status"] == "OK"
                           else f"потрібен адаптер для {ats}")
            c["notes"] = note
            continue
        res, used_net = probe(c["display"], cache, allow_network=(not args.no_probe and probes_left > 0))
        if used_net:
            probes_left -= 1
        if res and res.get("status") == "OK" and res.get("ats") in can_fetch:
            c["ats"], c["endpoint"], c["scan_status"] = res["ats"], res["endpoint"], "OK"
            c["action"], c["notes"] = "додано в сканування", res.get("notes", "")
        elif hint:  # own careers site
            c["ats"], c["endpoint"], c["scan_status"] = hint[0], hint[1], "MANUAL"
            c["action"], c["notes"] = f"свій сайт: потрібен адаптер ({host_of(hint[1])})", hint[2]
        elif res is None:
            c["ats"], c["endpoint"], c["scan_status"] = "?", "", "PENDING"
            c["action"], c["notes"] = "ATS ще не перевірено (запусти без --no-probe)", ""
        else:
            c["ats"], c["endpoint"], c["scan_status"] = res.get("ats") or "Unknown", "", "MANUAL"
            c["action"], c["notes"] = "ATS не знайдено: знайди сторінку вакансій вручну", res.get("notes", "")

    for c in add:
        check_endpoint(c, aliases, allow_network=not args.no_probe)

    # Re-check rows this script added earlier that were never verified.
    reverify = []
    for e in companies:
        if e.get("source") != "suggest_companies" or e.get("status") not in ("OK", "CHECK") or e.get("verified_on"):
            continue
        tmp = {"display": e["name"], "ats": e["ats"], "endpoint": e["endpoint"], "scan_status": "OK",
               "notes": e.get("notes", "")}
        check_endpoint(tmp, aliases, allow_network=not args.no_probe)
        reverify.append((e, tmp))

    # Rows already in the list that the rules now exclude (e.g. agencies).
    rule_excluded = [(e, excluded(k)) for k, e in existing.items()
                     if e.get("status") != "EXCLUDED" and excluded(k)]

    # Companies already scanned that bring nothing.
    remove = []
    for k, e in existing.items():
        if e.get("status") != "OK":
            continue
        tracker_live = comp.get(k, {}).get("status", Counter())
        live = sum(tracker_live.get(s, 0) for s in ("todo", "applied", "talk", "interview", "offer"))
        added_on = e.get("added_on")
        fresh = bool(added_on) and (TODAY - dt.date.fromisoformat(added_on)).days < window
        if agent_counts.get(k, 0) == 0 and live == 0 and not fresh and run_days >= window * 2 // 3:
            remove.append(e)

    # ---------- report ----------
    L = []
    L.append(f"# Які компанії сканувати - {TODAY.isoformat()}\n")
    L.append(f"Компаній у трекері: {len(comp)}. Додати: {len(add)}. Спостерігати: {len(watch)}. "
             f"Прибрати зі сканування: {len(remove)}. Режим: {'ЗАПИСАНО' if args.apply else 'тільки звіт'}.\n")
    L.append(f"Дані Agent 1 за {window} днів: {run_days} днів із запусками.\n")
    L.append("## Додати (бал >= %d)\n" % rules["thresholds"]["add"])
    L.append("| Компанія | Бал | Чому | ATS | Що робити |\n|---|---|---|---|---|")
    for c in add:
        L.append(f"| {c['display']} | {c['score']} | {why(c)} | {c.get('ats','')} | {c.get('action','')} |")
    L.append("\n## Спостерігати (бал %d-%d)\n" % (rules["thresholds"]["watch"], rules["thresholds"]["add"] - 1))
    L.append("| Компанія | Бал | Чому |\n|---|---|---|")
    for c in watch[:30]:
        L.append(f"| {c['display']} | {c['score']} | {why(c)} |")
    if len(watch) > 30:
        L.append(f"\nІ ще {len(watch) - 30} компаній з балом {rules['thresholds']['watch']}+ (здебільшого одна подача).")
    checks = [(c["display"], c.get("ats"), c.get("endpoint"), c.get("action")) for c in add if c.get("scan_status") == "CHECK"]
    checks += [(e["name"], e["ats"], e["endpoint"], t.get("action", "")) for e, t in reverify if t["scan_status"] == "CHECK"]
    L.append("\n## Перевір вручну (не скануються, поки не підтвердиш)\n")
    for n, ats, ep, why_ in checks:
        L.append(f"- {n}: {ats} {ep} - {why_}. Якщо це та компанія, зміни status на OK у data/companies.json.")
    if not checks:
        L.append("- нічого")
    L.append(f"\n## Прибрати зі сканування (0 нових вакансій за {window} днів і нічого в трекері)\n")
    for e in remove:
        L.append(f"- {e['name']} ({e['ats']})")
    if not remove:
        L.append("- нікого")
    L.append("\n## Уже в списку Agent 1\n")
    L.append("| Компанія | Статус у списку | Бал у трекері | Знайдено Agent 1 за %d днів |\n|---|---|---|---|" % window)
    for c, e in already:
        L.append(f"| {e['name']} | {e.get('status')} | {c['score']} | {agent_counts.get(norm(e['name'], aliases), 0)} |")
    L.append("\n## Виключено правилами (company_rules.json)\n")
    for e, reason in rule_excluded:
        L.append(f"- {e['name']} (було в списку, статус {e.get('status')}): {reason}")
    for c, reason in blocked:
        L.append(f"- {c['display']}: {reason}")
    OUT.mkdir(exist_ok=True)
    (OUT / "company_suggestions.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (DATA / "ats_cache.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- apply ----------
    if args.apply:
        bdir = DATA / "backups"
        bdir.mkdir(exist_ok=True)
        shutil.copy2(DATA / "companies.json", bdir / f"companies_{dt.datetime.now():%Y-%m-%d_%H%M}.json")
        added = 0
        for c in add:
            if c.get("scan_status") not in ("OK", "MANUAL", "CHECK"):
                continue
            companies.append({
                "name": c["display"], "ats": c["ats"], "endpoint": c["endpoint"], "status": c["scan_status"],
                "notes": c.get("notes", ""), "source": "suggest_companies", "added_on": TODAY.isoformat(),
                "score": c["score"], "job_count": None, "job_count_low_confidence": False,
                **({"verified_on": c["verified_on"]} if c.get("verified_on") else {}),
            })
            added += 1
        for e, tmp in reverify:
            e["status"], e["notes"] = tmp["scan_status"], tmp.get("notes", e.get("notes", ""))
            if tmp.get("verified_on"):
                e["verified_on"] = tmp["verified_on"]
        for e, reason in rule_excluded:
            e["status_before"], e["status"] = e.get("status"), "EXCLUDED"
            e["excluded_reason"], e["excluded_on"] = f"rule: {reason}", TODAY.isoformat()
        for e in remove:
            e["status_before"], e["status"] = e.get("status"), "EXCLUDED"
            e["excluded_reason"] = f"auto: 0 new matching roles in {window} days, nothing in tracker"
            e["excluded_on"] = TODAY.isoformat()
        (DATA / "companies.json").write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"companies.json updated: +{added} added, {len(remove) + len(rule_excluded)} excluded. Backup in data/backups/.")

    print(f"Report: out/company_suggestions.md | add {len(add)} | watch {len(watch)} | remove {len(remove)}")


if __name__ == "__main__":
    main()
