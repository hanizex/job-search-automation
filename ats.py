"""
ATS adapters for Agent 1 — six families in one module.

New file, 25.10.2026. Standard library only, Python 3.9+.
Add rows to data/companies.json with an "ats" key and call fetch_all() from boards.py.

Every adapter returns a list of dicts in the shape poll_jobs.py already consumes:
    {company, role, url, location, pay, board, posted, found}
posted is "YYYY-MM-DD" or "". found is today's date.

Design rules:
- One board failing never kills the run. Errors are collected and returned.
- 3 seconds between requests, same as boards.py.
- No third-party packages.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
TIMEOUT = 30
DELAY = 3.0
_last_call = [0.0]


# ---------------------------------------------------------------- helpers

def _sleep():
    gap = time.time() - _last_call[0]
    if gap < DELAY:
        time.sleep(DELAY - gap)
    _last_call[0] = time.time()


def _request(url, data=None, headers=None):
    _sleep()
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=hdrs)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _day(value):
    """Normalise anything date-like to YYYY-MM-DD, or ''."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        # Lever uses epoch milliseconds
        secs = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    # Workday writes "Posted 3 Days Ago" — no usable date in it
    return ""


def _today():
    return date.today().strftime("%Y-%m-%d")


def _row(company, role, url, location, posted, board, pay=""):
    return {
        "company": company,
        "role": (role or "").strip(),
        "url": url,
        "location": (location or "").strip(),
        "pay": pay or "",
        "board": board,
        "posted": _day(posted),
        "found": _today(),
    }


def _join(parts):
    seen, out = set(), []
    for p in parts:
        p = (p or "").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return "; ".join(out)


# ---------------------------------------------------------------- adapters

def fetch_greenhouse(cfg):
    """cfg: {name, token, host?}  host defaults to the US board API.

    EU-resident boards (JetBrains, Payhawk) need host "boards-api.eu.greenhouse.io".
    """
    host = cfg.get("host") or "boards-api.greenhouse.io"
    token = cfg["token"]
    url = f"https://{host}/v1/boards/{token}/jobs?content=true"
    data = _request(url)
    rows = []
    for job in data.get("jobs") or []:
        loc = (job.get("location") or {}).get("name", "")
        offices = [o.get("name", "") for o in (job.get("offices") or [])]
        rows.append(_row(
            cfg["name"],
            job.get("title"),
            job.get("absolute_url"),
            _join([loc] + offices),
            job.get("first_published") or job.get("updated_at"),
            "Greenhouse",
        ))
    return rows


def fetch_ashby(cfg):
    """cfg: {name, slug}.  Some slugs contain a dot, e.g. "checkout.com"."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{cfg['slug']}?includeCompensation=true"
    data = _request(url)
    rows = []
    for job in data.get("jobs") or []:
        if job.get("isListed") is False:
            continue
        secondary = [s.get("location", "") for s in (job.get("secondaryLocations") or [])]
        comp = job.get("compensation") or {}
        summary = comp.get("compensationTierSummary") or ""
        rows.append(_row(
            cfg["name"],
            job.get("title"),
            job.get("jobUrl"),
            _join([job.get("location")] + secondary),
            job.get("publishedAt"),
            "Ashby",
            summary,
        ))
    return rows


def fetch_lever(cfg):
    """cfg: {name, slug}"""
    url = f"https://api.lever.co/v0/postings/{cfg['slug']}?mode=json"
    data = _request(url)
    rows = []
    for job in data or []:
        cats = job.get("categories") or {}
        rows.append(_row(
            cfg["name"],
            job.get("text"),
            job.get("hostedUrl"),
            _join([cats.get("location"), cats.get("allLocations") and
                   "; ".join(cats.get("allLocations"))]),
            job.get("createdAt"),
            "Lever",
        ))
    return rows


def fetch_smartrecruiters(cfg):
    """cfg: {name, slug}  slug is the SmartRecruiters company id, e.g. "ServiceNow"."""
    slug = cfg["slug"]
    rows, offset = [], 0
    while True:
        url = (f"https://api.smartrecruiters.com/v1/companies/{slug}"
               f"/postings?limit=100&offset={offset}")
        data = _request(url)
        content = data.get("content") or []
        for job in content:
            loc = job.get("location") or {}
            bits = [loc.get("city"), loc.get("region"), loc.get("country")]
            if loc.get("remote"):
                bits.append("Remote")
            rows.append(_row(
                cfg["name"],
                job.get("name"),
                f"https://jobs.smartrecruiters.com/{slug}/{job.get('id')}",
                _join(bits),
                job.get("releasedDate"),
                "SmartRecruiters",
            ))
        offset += len(content)
        if not content or offset >= int(data.get("totalFound") or 0):
            break
    return rows


def fetch_recruitee(cfg):
    """cfg: {name, slug} or {name, url}.  Chaos serves its board from its own domain."""
    url = cfg.get("url") or f"https://{cfg['slug']}.recruitee.com/api/offers/"
    data = _request(url)
    rows = []
    for job in data.get("offers") or []:
        bits = [job.get("location"), job.get("city"), job.get("country")]
        for loc in job.get("locations") or []:
            if isinstance(loc, dict):
                bits.append(loc.get("city") or loc.get("name"))
        rows.append(_row(
            cfg["name"],
            job.get("title"),
            job.get("careers_url") or job.get("careers_apply_url"),
            _join(bits),
            job.get("published_at") or job.get("created_at"),
            "Recruitee",
        ))
    return rows


def fetch_workday(cfg):
    """cfg: {name, tenant, wd, site}

    POST to the CXS endpoint, 20 rows per page. This is the one adapter the cloud
    cannot run: the egress proxy refuses CONNECT to *.myworkdayjobs.com.
    """
    tenant, wd, site = cfg["tenant"], cfg["wd"], cfg["site"]
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    rows, offset, total = [], 0, None
    while True:
        payload = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}
        data = _request(api, data=payload)
        postings = data.get("jobPostings") or []
        if total is None:
            total = int(data.get("total") or 0)
        for job in postings:
            path = job.get("externalPath") or ""
            rows.append(_row(
                cfg["name"],
                job.get("title"),
                f"{base}/en-US/{site}{path}",
                job.get("locationsText"),
                "",  # Workday gives "Posted 3 Days Ago", not a date
                "Workday",
            ))
        offset += len(postings)
        if not postings or offset >= total or offset > 2000:
            break
    return rows


def verify_workday_job(url):
    """True if a Workday job URL is still open.

    The CXS GET detail endpoint answers even where POST is blocked, and a 404
    there reliably means the posting is closed. Cheap re-check for stale rows.
    """
    try:
        host, _, rest = url.partition("/en-US/")
        tenant = host.split("//", 1)[-1].split(".", 1)[0]
        site, _, path = rest.partition("/")
        _request(f"{host}/wday/cxs/{tenant}/{site}/job/{path}")
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    except (ValueError, IndexError):
        return True  # not a Workday URL we understand: do not judge it


# ---------------------------------------------------------------- dispatch

ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "ashby": fetch_ashby,
    "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
    "recruitee": fetch_recruitee,
    "workday": fetch_workday,
}


def fetch_all(companies, log=None):
    """companies: the list from data/companies.json.

    Only rows with an "ats" key in ADAPTERS and status "ok" are fetched.
    Returns (rows, errors). errors is a list of (company, message).
    """
    rows, errors = [], []
    for cfg in companies:
        kind = (cfg.get("ats") or "").lower()
        if kind not in ADAPTERS:
            continue
        if (cfg.get("status") or "ok").lower() != "ok":
            continue
        try:
            got = ADAPTERS[kind](cfg)
            rows.extend(got)
            if log:
                log(f"OK [{cfg['name']}] ({kind}): {len(got)}")
        except Exception as exc:  # one dead board must not stop the run
            errors.append((cfg.get("name", "?"), f"{type(exc).__name__}: {exc}"))
            if log:
                log(f"FAIL [{cfg.get('name', '?')}] ({kind}): {exc}")
    return rows, errors


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/companies.json"
    with open(path, encoding="utf-8") as fh:
        companies = json.load(fh)
    if isinstance(companies, dict):
        companies = companies.get("companies", [])
    got, errs = fetch_all(companies, log=lambda m: print(m, file=sys.stderr))
    print(json.dumps(got, ensure_ascii=False, indent=2))
    if errs:
        print(f"\n{len(errs)} board(s) failed:", file=sys.stderr)
        for name, msg in errs:
            print(f"  {name}: {msg}", file=sys.stderr)
