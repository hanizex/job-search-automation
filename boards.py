"""
boards.py - job-board adapters for Agent 1 (11.10.2026). Called from poll_jobs.py.

Reads public listing pages, the same pages a person sees, at a low rate (3 s between
requests, a few pages per day). Returns postings in poll_jobs' normalized shape:
    title, location, posted_display, posted_sort, apply, hiring_entity, source_board
so they go through the same title / location / age filters, job_filters.py and seen.json.

Active boards (daily):
  DEV.BG  - highest priority. Sofia office and hybrid are in scope (Mykola lives there).
  DOU     - RSS feeds per category.
  Djinni  - HTML listing (RSS has no company or location).
  My Manager - daily email digest read over IMAP (12.10), runs last.
Waiting-list boards (weekly volume count only, nothing emailed):
  Just Join IT, NoFluffJobs.
Blocked: jobs.bg (Cloudflare 403 for scripts) - not used.

Parsers were written against real pages saved by fetch_samples.py on 11.10.2026.
If a board changes its HTML, the adapter logs "0 postings" - check run.log.
Python 3.9 compatible; needs only requests.
"""
from __future__ import annotations

import html as H
import json
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, List, Optional

import requests

DELAY = 3.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

DEVBG_LISTS = [  # remote first, so a remote copy of a multi-city ad wins the dedupe
    "https://dev.bg/company/jobs/it-project-management/remote/",
    "https://dev.bg/company/jobs/pm-ba-and-more/remote/",
    "https://dev.bg/company/jobs/it-project-management/",
    "https://dev.bg/company/jobs/pm-ba-and-more/sofiya/",
]
DEVBG_MAX_PAGES = 3
DOU_FEEDS = [
    "https://jobs.dou.ua/vacancies/feeds/?category=Project%20Manager",
    "https://jobs.dou.ua/vacancies/feeds/?category=Product%20Manager",
]
DJINNI_LISTS = [
    "https://djinni.co/jobs/?primary_keyword=Project+Manager",
    "https://djinni.co/jobs/?primary_keyword=Product+Manager",
    "https://djinni.co/jobs/keyword-delivery_manager/",
]
DJINNI_MAX_PAGES = 3
WATCH_BOARDS = {
    "Just Join IT (remote PM)": "https://justjoin.it/job-offers/remote/pm",
    "NoFluffJobs (remote PM)": "https://nofluffjobs.com/pl/praca-zdalna/project-manager",
}

BG_MONTHS = {"яну": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "юни": 6, "юли": 7, "авг": 8,
             "сеп": 9, "окт": 10, "ное": 11, "дек": 12}
UA_CITIES = {"київ": "Kyiv", "львів": "Lviv", "харків": "Kharkiv", "дніпро": "Dnipro", "одеса": "Odesa",
             "вінниця": "Vinnytsia", "запоріжжя": "Zaporizhzhia", "івано-франківськ": "Ivano-Frankivsk",
             "тернопіль": "Ternopil", "чернівці": "Chernivtsi", "ужгород": "Uzhhorod", "луцьк": "Lutsk",
             "рівне": "Rivne", "житомир": "Zhytomyr", "полтава": "Poltava", "суми": "Sumy",
             "черкаси": "Cherkasy", "чернігів": "Chernihiv", "миколаїв": "Mykolaiv", "херсон": "Kherson",
             "хмельницький": "Khmelnytskyi", "кропивницький": "Kropyvnytskyi", "біла церква": "Bila Tserkva"}
UKRAINE_ONLY_TEXT = re.compile(
    r"(тільки|лише|виключно)\s+(з|в|у)\s+україн|перебувати\s+(в|у)\s+україн|"
    r"only\s+(candidates\s+)?(from|in|based in)\s+ukraine|must\s+be\s+(based|located)\s+in\s+ukraine", re.I)


def _get(url: str) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
    except requests.RequestException:
        return None
    finally:
        time.sleep(DELAY)
    return r


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _posting(title, location, dt, url, company, board) -> dict:
    return dict(title=title or "UNKNOWN", location=location or "UNKNOWN",
                posted_display=dt.date().isoformat() if dt else "UNKNOWN", posted_sort=dt,
                apply=url or "UNKNOWN", hiring_entity=company or "UNKNOWN", source_board=board)


# ------------------------------------------------------------------ DEV.BG
def _devbg_date(s: str) -> Optional[datetime]:
    m = re.match(r"\s*(\d{1,2})\s+([а-я]{3})", (s or "").lower())
    if not m or m.group(2) not in BG_MONTHS:
        return None
    today = date.today()
    d, mon = int(m.group(1)), BG_MONTHS[m.group(2)]
    year = today.year if (mon, d) <= (today.month, today.day) else today.year - 1
    try:
        return datetime(year, mon, d)
    except ValueError:
        return None


def _devbg_location(badges: list, langs: list) -> str:
    joined = " ".join(badges)
    if "Remote" in joined:
        loc = "Remote, Bulgaria"
    elif "София" in joined or "Sofia" in joined:
        loc = "Sofia, Bulgaria" + (" (Hybrid)" if "Hybrid" in joined else "")
    else:  # another Bulgarian city, office: not Sofia, goes to the relocation watch
        city = badges[0].replace("Hybrid", "").strip() if badges else "office"
        loc = f"{city} (office, outside Sofia)"
    if "Bulgarian" in langs:
        loc += " [Bulgarian in requirements]"
    return loc


def parse_devbg(page_html: str) -> List[dict]:
    out = []
    for p in re.split(r'<div class="job-list-item', page_html)[1:]:
        url = re.search(r'href="(https://dev\.bg/company/jobads/[^"]+)"', p)
        title = re.search(r'<h6 class="job-title[^"]*">(.*?)</h6>', p, re.S)
        comp = re.search(r'<span class="company-name[^"]*">(.*?)</span>', p, re.S)
        date_s = re.search(r'<span class="date[^"]*">(.*?)</span>', p, re.S)
        badges = [_text(b) for b in re.findall(r'<span class="\s*badge[^"]*">(.*?)</span>', p, re.S)]
        langs = re.findall(r'tech-stack-item[^>]*>\s*<img[^>]*title="([^"]+)"', p)
        if not (url and title):
            continue
        t = _text(title.group(1))
        foreign = [l for l in langs if l in ("German", "French", "Italian", "Dutch", "Polish", "Spanish",
                                             "Greek", "Czech", "Romanian", "Hungarian", "Turkish")]
        if foreign and not re.search("|".join(foreign), t, re.I):
            t += f" (with {foreign[0]})"  # job_filters drops language-in-title rows
        out.append(_posting(t, _devbg_location(badges, langs), _devbg_date(date_s.group(1) if date_s else ""),
                            url.group(1), _text(comp.group(1)) if comp else "", "DEV.BG"))
    return out


def fetch_devbg(log: Callable[[str], None]) -> List[dict]:
    rows, seen = [], set()
    for base in DEVBG_LISTS:
        for page in range(1, DEVBG_MAX_PAGES + 1):
            url = base if page == 1 else f"{base}?_paged={page}"
            r = _get(url)
            if r is None or r.status_code != 200:
                log(f"DEV.BG: {url} -> {getattr(r, 'status_code', 'request failed')}")
                break
            found = parse_devbg(r.text)
            for p in found:
                key = (p["hiring_entity"].lower(), re.sub(r"\W+", " ", p["title"].lower()).strip())
                if key in seen:  # same ad in several cities, or listed in two categories
                    continue
                seen.add(key)
                rows.append(p)
            if f"_paged={page + 1}" not in r.text:
                break
    return rows


# ------------------------------------------------------------------ DOU
UA_COUNTRY_NAMES = {"кіпр": "Cyprus", "велика британія": "United Kingdom", "польща": "Poland",
                    "німеччина": "Germany", "іспанія": "Spain", "португалія": "Portugal", "болгарія": "Bulgaria",
                    "нідерланди": "Netherlands", "естонія": "Estonia", "литва": "Lithuania", "латвія": "Latvia",
                    "чехія": "Czech Republic", "румунія": "Romania", "мальта": "Malta", "оае": "United Arab Emirates",
                    "сша": "USA", "грузія": "Georgia", "вірменія": "Armenia", "ізраїль": "Israel", "франція": "France",
                    "італія": "Italy", "австрія": "Austria", "словаччина": "Slovakia", "угорщина": "Hungary"}


def _dou_location(parts: list, desc: str) -> str:
    low = [x.lower().strip() for x in parts]
    remote = any("віддалено" in x for x in low)
    abroad = any("за кордоном" in x for x in low)
    cities = [UA_CITIES[x] for x in low if x in UA_CITIES]
    if UKRAINE_ONLY_TEXT.search(desc or ""):
        return "Ukraine (Remote)" if remote else "Ukraine"
    if abroad:
        return "Abroad / Europe (DOU: за кордоном)"
    if remote:
        return "Remote (DOU: country not stated)"
    if cities:
        return ", ".join(cities) + ", Ukraine"
    abroad_countries = [en for ua, en in UA_COUNTRY_NAMES.items() if any(ua in x for x in low)]
    if abroad_countries:
        return ", ".join(parts) + " - " + ", ".join(abroad_countries)
    return ", ".join(parts) or "UNKNOWN"


def parse_dou_rss(xml: str, default_company: str = "") -> List[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        raw = H.unescape(H.unescape(re.search(r"<title>(.*?)</title>", it, re.S).group(1))).strip()
        link = re.search(r"<link>(.*?)</link>", it, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
        desc = _text(H.unescape((re.search(r"<description>(.*?)</description>", it, re.S) or [None, ""])[1]))
        if " в " in raw:
            role, rest = raw.rsplit(" в ", 1) if raw.count(" в ") == 1 else raw.split(" в ", 1)
            bits = [b.strip() for b in rest.split(",")]
            company, tail = bits[0], bits[1:]
        elif default_company:  # company feed: the title may carry no " в Company" part
            bits = [b.strip() for b in raw.split(",")]
            role, company, tail = bits[0], default_company, bits[1:]
        else:
            continue
        salary = [b for b in tail if re.match(r"^[\$€₴]?\s?\d", b)]
        places = [b for b in tail if b not in salary]
        try:
            dt = parsedate_to_datetime(pub.group(1)).astimezone(timezone.utc).replace(tzinfo=None) if pub else None
        except (TypeError, ValueError):
            dt = None
        url = (link.group(1).strip().split("?")[0]) if link else ""
        loc = _dou_location(places, desc) + (f" · {salary[0]}" if salary else "")
        post = _posting(role.strip(), loc, dt, url, company, "DOU")
        if desc:
            post["_jd_embedded"] = desc   # Stage A (13.10): RSS snippet; jd_fetch reads the page if it is too short
        out.append(post)
    return out


def fetch_dou_companies(log: Callable[[str], None], feeds_path: Path = Path("data/dou_company_feeds.json")) -> List[dict]:
    """Company vacancy feeds on DOU (jobs.dou.ua/vacancies/<slug>/feeds/) for the Ukrainian-rooted list (12.10)."""
    try:
        feeds = json.loads(feeds_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    rows, empty = [], 0
    for f in feeds:
        url = f"https://jobs.dou.ua/vacancies/{f['slug']}/feeds/"
        r = _get(url)
        if r is None or r.status_code != 200:
            log(f"DOU company feed {f['name']}: {getattr(r, 'status_code', 'request failed')}")
            continue
        got = parse_dou_rss(r.text, default_company=f["name"])
        empty += 0 if got else 1
        rows.extend(got)
    log(f"DOU company feeds: {len(feeds)} read, {empty} empty")
    return rows


def fetch_dou(log: Callable[[str], None]) -> List[dict]:
    rows, seen = [], set()
    for feed in DOU_FEEDS:
        r = _get(feed)
        if r is None or r.status_code != 200:
            log(f"DOU: {feed} -> {getattr(r, 'status_code', 'request failed')}")
            continue
        for p in parse_dou_rss(r.text):
            if p["apply"] not in seen:
                seen.add(p["apply"])
                rows.append(p)
    return rows


# ------------------------------------------------------------------ Djinni
def _djinni_location(meta: list) -> str:
    mode = next((m for m in meta if m in ("Full Remote", "Hybrid Remote", "Office Work", "Part-time")), "")
    modes = [m for m in meta if m in ("Full Remote", "Hybrid Remote", "Office Work")]
    place = next((m for m in meta if m not in ("Full Remote", "Hybrid Remote", "Office Work", "Part-time")
                  and not re.search(r"experience|English|^No experience", m)), "")
    pl = place.lower()
    if "Full Remote" in modes and re.search(r"worldwide|europe|\beu\b", pl):
        loc = "Remote - Europe" if "europe" in pl or re.search(r"\beu\b", pl) else "Remote - Worldwide"
    elif "Full Remote" in modes and pl.startswith("ukraine"):
        loc = "Ukraine (Remote)"
    elif "Full Remote" in modes and place:
        loc = f"{place} (Remote)"
    elif "ukraine" in pl:
        loc = "Ukraine"
    elif re.search(r"worldwide|europe|\beu\b", pl):
        loc = f"Remote - {place} (work mode not stated)"
    else:
        loc = place or "UNKNOWN"
    if "Part-time" in meta:
        loc += " · part-time"
    return loc


def parse_djinni(page_html: str) -> List[dict]:
    out = []
    for b in re.split(r'<div id="job-item-', page_html)[1:]:
        href = re.search(r'href="(/jobs/\d+[^"]*)"', b)
        title = re.search(r"job-item__position[^>]*>(.*?)</h2>", b, re.S)
        comp = re.search(r'<span class="small text-gray-800[^"]*">(.*?)</span>', b, re.S)
        meta_m = re.search(r'<div class="fw-medium d-flex flex-wrap[^"]*">(.*?)</div>', b, re.S)
        meta = [_text(x).strip(" ·") for x in re.split(r'<span class="middot">', meta_m.group(1))] if meta_m else []
        meta = [m for m in meta if m]
        sal = re.search(r'title="Salary level[^"]*"\s*>([^<]+)<', b)
        dt_m = re.search(r'title="(\d{2}:\d{2} \d{2}\.\d{2}\.\d{4})"', b)
        if not (href and title):
            continue
        try:
            dt = datetime.strptime(dt_m.group(1), "%H:%M %d.%m.%Y") if dt_m else None
        except ValueError:
            dt = None
        loc = _djinni_location(meta) + (f" · {sal.group(1).strip()}" if sal else "")
        out.append(_posting(_text(title.group(1)), loc, dt, "https://djinni.co" + href.group(1),
                            _text(comp.group(1)) if comp else "", "Djinni"))
    return out


def fetch_djinni(log: Callable[[str], None]) -> List[dict]:
    rows, seen = [], set()
    for base in DJINNI_LISTS:
        for page in range(1, DJINNI_MAX_PAGES + 1):
            sep = "&" if "?" in base else "?"
            url = base if page == 1 else f"{base}{sep}page={page}"
            r = _get(url)
            if r is None or r.status_code != 200:
                log(f"Djinni: {url} -> {getattr(r, 'status_code', 'request failed')}")
                break
            found = parse_djinni(r.text)
            fresh = [p for p in found if p["apply"] not in seen]
            for p in fresh:
                seen.add(p["apply"])
                rows.append(p)
            if not found or not fresh:
                break
    return rows


# ------------------------------------------------------------------ iGaming company sites (12.10)
TEAMTAILOR_FEEDS = {"EveryMatrix": "https://everymatrix.teamtailor.com/jobs.rss"}
SOFTSWISS_URLS = ["https://careers.softswiss.com/wp-json/wp/v2/vacancies?per_page=100",
                  "https://careers.softswiss.com/vacancies/"]
DELASPORT_URL = "https://www.delasport.com/careers/"
EGT_URL = "https://egt-digital.com/careers/"
UPLATFORM_URL = "https://job.uplatform.com/"


def _slug_title(slug: str) -> str:
    slug = re.sub(r"^\d+-", "", slug.strip("/").split("/")[-1].split("?")[0])
    slug = re.sub(r"-\d{6,}$", "", slug)
    slug = re.sub(r"-\d{1,2}$", "", slug)
    return " ".join(w.upper() if w in ("po", "pm", "qa", "ui", "ux", "ai", "seo", "crm") else w.capitalize()
                    for w in re.split(r"[-_]+", slug) if w)


def parse_teamtailor_rss(xml: str, company: str) -> List[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = _text((re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1])
        link = (re.search(r"<link>(.*?)</link>", it, re.S) or [None, ""])[1].strip()
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
        remote = (re.search(r"<remoteStatus>(.*?)</remoteStatus>", it) or [None, ""])[1].strip().lower()
        cities = re.findall(r"<tt:city>(.*?)</tt:city>", it)
        countries = re.findall(r"<tt:country>(.*?)</tt:country>", it)
        places = list(dict.fromkeys(f"{c}, {k}" for c, k in zip(cities, countries))) or countries
        loc = "; ".join(places) or "UNKNOWN"
        if remote == "fully":
            loc += " (Remote)"
        elif remote == "hybrid":
            loc += " (Hybrid)"
        try:
            dt = parsedate_to_datetime(pub.group(1)).astimezone(timezone.utc).replace(tzinfo=None) if pub else None
        except (TypeError, ValueError):
            dt = None
        out.append(_posting(title, loc, dt, link, company, company))
    return out


def parse_softswiss(text: str) -> List[dict]:
    rows = []
    if text.lstrip().startswith("["):  # WordPress REST answer
        try:
            for v in json.loads(text):
                title = _text((v.get("title") or {}).get("rendered", ""))
                try:
                    dt = datetime.fromisoformat(v.get("date", "")[:19])
                except ValueError:
                    dt = None
                rows.append(_posting(title, "SOFTSWISS (location on the page)", dt, v.get("link", ""), "SOFTSWISS", "SOFTSWISS"))
        except ValueError:
            pass
        return rows
    for url in sorted(set(re.findall(r'href="(https://careers\.softswiss\.com/vacancies/[a-z0-9-]+/)"', text))):
        rows.append(_posting(_slug_title(url), "SOFTSWISS (location on the page)", None, url, "SOFTSWISS", "SOFTSWISS"))
    return rows


def parse_delasport(page: str) -> List[dict]:
    rows, seen = [], set()
    for card in re.split(r'<div class="job-item"', page)[1:]:
        url = re.search(r'href="(https://www\.delasport\.com/job/[^"]+)"', card)
        title = re.search(r"<h3>(.*?)</h3>", card, re.S)
        loc = re.search(r'<span class="job-location">(.*?)</span>', card, re.S)
        if not url or url.group(1) in seen:
            continue
        seen.add(url.group(1))
        place = _text(loc.group(1)) if loc else "Sofia, Bulgaria"
        rows.append(_posting(_text(title.group(1)) if title else _slug_title(url.group(1)),
                             place, None, url.group(1), "Delasport", "Delasport"))
    return rows


def parse_egt(page: str) -> List[dict]:
    urls = sorted(set(u.split("?")[0] for u in re.findall(r'href="(https://egt-digital\.skillie\.ai/jobs/[^"]+)"', page)))
    return [_posting(_slug_title(u), "Sofia, Bulgaria (EGT Digital)", None, u, "EGT Digital", "EGT Digital") for u in urls]


def parse_uplatform(page: str) -> List[dict]:
    skip = {"turnkey", "games-aggregator", "about", "contacts", "blog"}
    slugs = sorted(set(re.findall(r'href="/([a-z0-9_-]+)"', page)) - skip)
    return [_posting(_slug_title(s), "Remote (Uplatform: country not stated)", None,
                     f"https://job.uplatform.com/{s}", "Uplatform", "Uplatform") for s in slugs]


def fetch_igaming_sites(log: Callable[[str], None]) -> List[dict]:
    rows = []
    for company, url in TEAMTAILOR_FEEDS.items():
        r = _get(url)
        got = parse_teamtailor_rss(r.text, company) if r is not None and r.status_code == 200 else []
        log(f"iGaming {company} (Teamtailor RSS): {len(got)}")
        rows += got
    for url in SOFTSWISS_URLS:
        r = _get(url)
        got = parse_softswiss(r.text) if r is not None and r.status_code == 200 else []
        log(f"iGaming SOFTSWISS ({url.split('/')[3]}): {len(got)}")
        if got:
            rows += got
            break
    for name, url, fn in (("Delasport", DELASPORT_URL, parse_delasport), ("EGT Digital", EGT_URL, parse_egt),
                          ("Uplatform", UPLATFORM_URL, parse_uplatform)):
        r = _get(url)
        got = fn(r.text) if r is not None and r.status_code == 200 else []
        log(f"iGaming {name}: {len(got)}")
        rows += got
    return rows


# ------------------------------------------------------------------ waiting-list volume
def count_watch_board(page_html: str) -> int:
    urls = set(re.findall(r'"url":"(https://justjoin\.it/job-offer/[^"]+)"', page_html))
    if urls:
        return len(urls)
    m = re.findall(r'"totalCount"\s*:\s*(\d+)', page_html)
    if m:
        return max(int(x) for x in m)
    return len(set(re.findall(r'href="(/pl/job/[^"]+)"', page_html)))


def update_market_watch(log: Callable[[str], None], data_dir: Path, out_dir: Path, every_days: int = 7) -> None:
    path = data_dir / "market_watch.json"
    try:
        watch = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        watch = {}
    today = date.today().isoformat()
    last = watch.get("_last_run")
    if last and (date.today() - date.fromisoformat(last)).days < every_days:
        return
    for name, url in WATCH_BOARDS.items():
        r = _get(url)
        n = count_watch_board(r.text) if (r is not None and r.status_code == 200) else None
        watch.setdefault(name, []).append({"date": today, "count": n})
        log(f"Market watch: {name} -> {n if n is not None else 'failed'}")
    watch["_last_run"] = today
    path.write_text(json.dumps(watch, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Ринки в очікуванні ({today})", "",
             "Раз на тиждень рахуємо, скільки вакансій на дошках, які зараз не скануються.", "",
             "| Дошка | Дата | Вакансій на першій сторінці |", "|---|---|---|"]
    for name in WATCH_BOARDS:
        for rec in watch.get(name, [])[-8:]:
            lines.append(f"| {name} | {rec['date']} | {rec['count']} |")
    (out_dir / "market_watch.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ My Manager email digest (12.10)
# digest@mymgr.app sends a daily email at ~08:00 Sofia to the same Gmail that sends Agent 1's
# digest. Read over IMAP with the same app password (.env SMTP_USER / SMTP_PASS), read-only.
# Looks back MYMGR_DAYS days, so a digest that arrives after the run is picked up next day
# (seen.json stops repeats). Links point to mymgr.app, not the original posting, so this
# source runs LAST: the same job from DOU / Djinni wins the cross-source dedupe.
MYMGR_SENDER = "digest@mymgr.app"
MYMGR_DAYS = 3


def _load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def parse_mymgr_email(raw: bytes) -> List[dict]:
    import email
    from email import policy
    msg = email.message_from_bytes(raw, policy=policy.default)
    try:
        dt = parsedate_to_datetime(msg["Date"])
    except Exception:
        dt = None
    part = msg.get_body(preferencelist=("html",))
    body = part.get_content() if part else ""
    out = []
    for art in re.findall(r"<article>(.*?)</article>", body, re.S):
        a = re.search(r'<h2>(.*?)<a href="([^"]+)">(.*?)</a>', art, re.S)
        meta = re.search(r"<p>(.*?)</p>", art, re.S)
        if not a:
            continue
        score = re.search(r"(\d+)", _text(a.group(1)))
        title, url = _text(a.group(3)), H.unescape(a.group(2))
        bits = [b.strip() for b in _text(meta.group(1) if meta else "").split(" · ")]
        company = bits[0] if bits else ""
        board = bits[1] if len(bits) > 1 else "?"
        parts = [x.strip() for x in " · ".join(bits[2:]).split(",") if x.strip()]
        loc = _dou_location(parts, "").replace("(DOU:", "(MyMgr/%s:" % board)
        if score:
            loc += " · MyMgr score %s" % score.group(1)
        out.append(_posting(title, loc, dt, url, company, "MyMgr (%s)" % board))
    return out


def fetch_mymgr(log: Callable[[str], None], env_path: Path = Path(".env")) -> List[dict]:
    import imaplib
    from datetime import timedelta
    env = _load_env(env_path)
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    rows = []
    try:
        m.login(env["SMTP_USER"], env["SMTP_PASS"])
        if m.select('"[Gmail]/All Mail"', readonly=True)[0] != "OK":
            m.select("INBOX", readonly=True)
        since = (date.today() - timedelta(days=MYMGR_DAYS)).strftime("%d-%b-%Y")
        status, data = m.uid("search", None, "FROM", '"%s"' % MYMGR_SENDER, "SINCE", since)
        uids = data[0].split() if status == "OK" and data and data[0] else []
        for uid in uids:
            status, msgdata = m.uid("fetch", uid, "(BODY.PEEK[])")
            if status == "OK" and msgdata and msgdata[0]:
                rows.extend(parse_mymgr_email(msgdata[0][1]))
        log("MyMgr: %d digest email(s) in the last %d days, %d role(s) parsed" % (len(uids), MYMGR_DAYS, len(rows)))
        if uids and not rows:
            log("WARNING MyMgr: digest email(s) found but 0 roles parsed - the email format may have changed; "
                "run fetch_mymgr_samples.py and ask Claude to update parse_mymgr_email")
    finally:
        try:
            m.logout()
        except Exception:
            pass
    seen, uniq = set(), []
    for r in rows:  # the same job can repeat in several digests
        if r["apply"] not in seen:
            seen.add(r["apply"])
            uniq.append(r)
    return uniq


# ------------------------------------------------------------------ LinkedIn job-alert emails (14.10)
# jobalerts-noreply@linkedin.com = alerts Mykola set up himself -> title filter is skipped (trusted_title).
# jobs-noreply@linkedin.com = LinkedIn's own recommendations -> normal title filter.
# Same IMAP route and app password as My Manager. Read-only, 3-day lookback; seen.json stops repeats.
LI_SENDERS = {"jobalerts-noreply@linkedin.com": True, "jobs-noreply@linkedin.com": False}
LI_VIEW = re.compile(r"(?:Переглянути вакансію|View job|Посмотреть вакансию|Вижте обявата)\s*:\s*"
                     r"https://www\.linkedin\.com/comm/jobs/view/(\d+)")
LI_NOISE = re.compile(r"(контакт|connection|Подати заявку|Easy Apply|Apply with|Нова вакансія|New job|Сповіщення про|"
                      r"Job alert|Рекомендації|Recommended|Розгорнути пошук|для пошуку вакансій|Активно наймає|"
                      r"Actively recruiting|Просува|Promoted|кандидат|applicant|відгук|http|^-+$|Premium)", re.I)


def parse_linkedin_alert(raw: bytes) -> List[dict]:
    import email
    from email import policy
    msg = email.message_from_bytes(raw, policy=policy.default)
    try:
        dt = parsedate_to_datetime(msg["Date"])
    except Exception:
        dt = None
    sender = (msg.get("From") or "").lower()
    trusted = any(k in sender for k, v in LI_SENDERS.items() if v)
    part = msg.get_body(preferencelist=("plain",))
    text = part.get_content() if part else ""
    out, last = [], 0
    for m in LI_VIEW.finditer(text):
        chunk = text[last:m.start()]
        last = m.end()
        lines = [ln.strip() for ln in chunk.splitlines()]
        lines = [ln for ln in lines if ln and not LI_NOISE.search(ln)]
        if len(lines) < 2:
            continue
        lines = lines[-4:] if len(lines) > 3 else lines
        # the job card is the last 3 clean lines before the link: title, company, location
        title, company, loc = (lines[-3], lines[-2], lines[-1]) if len(lines) >= 3 else (lines[0], lines[1], "")
        row = _posting(title, (loc or "UNKNOWN") + " (LinkedIn alert)", dt,
                       "https://www.linkedin.com/jobs/view/%s/" % m.group(1), company, "LinkedIn alert")
        row["trusted_title"] = trusted
        out.append(row)
    return out


def fetch_linkedin_alerts(log: Callable[[str], None], env_path: Path = Path(".env")) -> List[dict]:
    import imaplib
    from datetime import timedelta
    env = _load_env(env_path)
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    rows, n = [], 0
    try:
        m.login(env["SMTP_USER"], env["SMTP_PASS"])
        if m.select('"[Gmail]/All Mail"', readonly=True)[0] != "OK":
            m.select("INBOX", readonly=True)
        since = (date.today() - timedelta(days=MYMGR_DAYS)).strftime("%d-%b-%Y")
        for snd in LI_SENDERS:
            status, data = m.uid("search", None, "FROM", '"%s"' % snd, "SINCE", since)
            for uid in (data[0].split() if status == "OK" and data and data[0] else []):
                status, md = m.uid("fetch", uid, "(BODY.PEEK[])")
                if status == "OK" and md and md[0]:
                    n += 1
                    rows.extend(parse_linkedin_alert(md[0][1]))
        log("LinkedIn alerts: %d email(s) in the last %d days, %d role(s) parsed" % (n, MYMGR_DAYS, len(rows)))
        if n and not rows:
            log("WARNING LinkedIn alerts: emails found but 0 roles parsed - format may have changed; "
                "run fetch_alert_samples.py and ask Claude to update parse_linkedin_alert")
    finally:
        try:
            m.logout()
        except Exception:
            pass
    seen, uniq = set(), []
    for r in rows:
        if r["apply"] not in seen:
            seen.add(r["apply"])
            uniq.append(r)
    return uniq


def fetch_all(log: Callable[[str], None]) -> List[dict]:
    rows = []
    for name, fn in (("DEV.BG", fetch_devbg), ("DOU", fetch_dou), ("Djinni", fetch_djinni),
                     ("DOU companies", fetch_dou_companies), ("iGaming sites", fetch_igaming_sites),
                     ("My Manager email", fetch_mymgr), ("LinkedIn alerts", fetch_linkedin_alerts)):
        try:
            got = fn(log)
        except Exception as e:  # a broken board must never kill the run
            log(f"FAILED board {name}: {e!r}")
            continue
        log(f"OK [{name}] (board): {len(got)} posting(s) fetched")
        rows.extend(got)
    return rows
