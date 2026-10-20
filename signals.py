"""
signals.py - funding / grant signals for consulting and job leads (12.10.2026).

Reads European, CEE and Ukrainian startup news feeds once a day, keeps only items that say
a company got money (round, investment, grant), extracts company / amount / round / country /
sector, tags priority sectors, and writes:
  data/signals_pool.json      - everything seen in the last 30 days (dedupe)
  out/signals_latest.json     - last 14 days, for the tracker's "Інвестиції" tab (autoimport)
  out/signals_latest.md       - human-readable list
Decisions (Mykola, 12.10): regions Europe + Ukraine + Bulgaria/CEE (USA later); all amounts;
priority sectors iGaming, E-commerce, EdTech, HRTech, FinTech, Payments, Mobile apps, R&D, AI;
everything else goes to the watch list. Big grants / big rounds are flagged as EUR 200/h candidates.
No AI. Python 3.9, needs only requests.
"""
from __future__ import annotations

import html as H
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, List, Optional

import requests

FEEDS = {  # verified 12.10 with fetch_funding_samples.py
    "EU-Startups": "https://www.eu-startups.com/feed/",
    "Tech.eu": "https://tech.eu/feed/",
    "The Recursive": "https://therecursive.com/feed/",
    "Trending Topics": "https://www.trendingtopics.eu/feed/",
    "Sifted": "https://sifted.eu/feed",
    "Crunchbase News": "https://news.crunchbase.com/feed/",
    "AIN.ua": "https://ain.ua/feed/",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
KEEP_POOL_DAYS, KEEP_OUT_DAYS = 30, 14

MONEY_VERB = re.compile(
    r"\b(raises?|raised|secures?|secured|bags|lands|captures|closes|nets|grabs|snags|receives|attracts|"
    r"lands|gets|wins|awarded|backs|invests? in|funding|investment|holt|erhält|sammelt|"
    r"залучи\w*|інвестува\w*|отрима\w* (?:грант|інвестиц\w*|фінансуван\w*)|раунд\w*|грант\w*)\b", re.I)
AMOUNT = re.compile(
    r"([€$£])\s?(\d+(?:[.,]\d+)?)\s?(m|mn|million|b|bn|billion|k)?\b|"
    r"(\d+(?:[.,]\d+)?)\s?(million|mio\.?|millionen|billion|mrd\.?|млн|млрд)\s?(euro|eur|€|dollars|usd|\$|£|доларів|євро)?",
    re.I)
ROUND = re.compile(r"\b(pre-seed|seed|series [a-f]\+?|pre-series [a-f]|growth|bridge|grant|грант|"
                   r"раунд\w* (?:pre-seed|seed|[a-f]))\b", re.I)
SKIP_TITLE = re.compile(r"round-?up|top \d+|recap|weekly|biggest|report|deals you need|data shows|"
                        r"quarter|q[1-4] |h[12] 20|підсумки|european startups|startups raise|^how |fund i{1,3}\b|debut fund|new fund|fund ii", re.I)
INVESTOR_WORDS = re.compile(r"\b(capital|ventures|partners|fund|vc|investors?)\b", re.I)
GRANT = re.compile(r"\bgrant|eic accelerator|horizon europe|brave1|грант|innovation fund\b", re.I)
SECTORS = [
    ("iGaming", r"igaming|gambling|betting|casino|sportsbook|lottery"),
    ("Payments", r"payment|payments|paytech|checkout|acquiring|pay\b|платіж"),
    ("FinTech", r"fintech|banking|neobank|lending|wealth|insurtech|finance|financial|фінтех"),
    ("E-commerce", r"e-?commerce|retail|marketplace|shopping|commerce|d2c|consumer brand"),
    ("EdTech", r"edtech|education|learning|school|tutor|освіт"),
    ("HRTech", r"hrtech|\bhr\b|hiring|recruit|workforce|payroll|talent"),
    ("Mobile apps", r"mobile app|\bapp\b|apps\b"),
    ("AI", r"\bai\b|artificial intelligence|agentic|llm|machine learning|генеративн|ші\b|штучн"),
    ("R&D", r"deep ?tech|r&d|research|quantum|biotech|space ?tech|semiconductor|robotics|defen[cs]e ?tech|deftech"),
]
PRIORITY_SECTORS = {"iGaming", "E-commerce", "EdTech", "HRTech", "FinTech", "Payments", "Mobile apps", "R&D", "AI"}
COUNTRY_HINTS = {
    "bulgaria": "Bulgaria", "bulgarian": "Bulgaria", "sofia": "Bulgaria", "ukrain": "Ukraine", "україн": "Ukraine",
    "kyiv": "Ukraine", "romania": "Romania", "romanian": "Romania", "poland": "Poland", "polish": "Poland",
    "estonia": "Estonia", "estonian": "Estonia", "latvia": "Latvia", "lithuania": "Lithuania", "slovak": "Slovakia",
    "czech": "Czechia", "croatia": "Croatia", "serbia": "Serbia", "hungar": "Hungary", "slovenia": "Slovenia",
    "macedonia": "North Macedonia", "greece": "Greece", "greek": "Greece", "germany": "Germany", "german": "Germany",
    "berlin": "Germany", "munich": "Germany", "austria": "Austria", "vienna": "Austria", "france": "France",
    "french": "France", "paris": "France", "spain": "Spain", "spanish": "Spain", "madrid": "Spain",
    "barcelona": "Spain", "italy": "Italy", "italian": "Italy", "portugal": "Portugal", "lisbon": "Portugal",
    "netherlands": "Netherlands", "dutch": "Netherlands", "amsterdam": "Netherlands", "belgi": "Belgium",
    "ghent": "Belgium", "brussels": "Belgium", "switzerland": "Switzerland", "swiss": "Switzerland",
    "zurich": "Switzerland", "bern": "Switzerland", "uk-": "UK", "london": "UK", "british": "UK",
    "ireland": "Ireland", "irish": "Ireland", "dublin": "Ireland", "sweden": "Sweden", "swedish": "Sweden",
    "stockholm": "Sweden", "norway": "Norway", "norwegian": "Norway", "denmark": "Denmark", "danish": "Denmark",
    "copenhagen": "Denmark", "finland": "Finland", "finnish": "Finland", "helsinki": "Finland",
    "cyprus": "Cyprus", "malta": "Malta",
}
US_HINTS = re.compile(r"\b(us-based|u\.s\.|san francisco|new york|silicon valley|california|boston|austin|seattle|"
                      r"north america|beijing|china|chinese|india|singapore)\b", re.I)
PREFIX_JUNK = re.compile(
    r"^(exclusive:\s*|profitable\s+|[a-z\- ]*-based\s+|[a-z\- ]*-founded\s+|[A-Z][a-z]+(?:’|')s\s+|"
    r"(?:bulgarian|ukrainian|romanian|polish|estonian|latvian|lithuanian|slovak|czech|croatian|serbian|"
    r"hungarian|greek|german|austrian|french|spanish|italian|portuguese|dutch|belgian|swiss|british|irish|"
    r"swedish|norwegian|danish|finnish|berliner|london|paris)\s+(?:[a-z\- ]+\s)?(?:startup|scale-?up|company|firm)?\s*)",
    re.I)


def _get(url: str) -> Optional[requests.Response]:
    try:
        return requests.get(url, headers=HEADERS, timeout=25)
    except requests.RequestException:
        return None
    finally:
        time.sleep(2)


def _clean(s: str) -> str:
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", H.unescape(s)))).strip()


def to_eur_millions(m: re.Match) -> Optional[float]:
    if m.group(1):  # symbol first: €5M / $4.2 million
        cur, num, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
    else:
        num, unit, cur = m.group(4), (m.group(5) or "").lower(), (m.group(6) or "€").lower()
    try:
        v = float(num.replace(",", "."))
    except ValueError:
        return None
    if unit in ("b", "bn", "billion", "mrd", "mrd.", "млрд"):
        v *= 1000
    elif unit == "k":
        v /= 1000
    elif unit == "" and v > 1000:  # "€500,000" style
        v /= 1_000_000
    rate = 0.92 if "$" in cur or "dollar" in cur or "usd" in cur or "долар" in cur else (1.17 if "£" in cur else 1.0)
    return round(v * rate, 2)


NATIONALITY = re.compile(
    r"^(?:bulgarian|ukrainian|romanian|polish|estonian|latvian|lithuanian|slovak|czech|croatian|serbian|"
    r"hungarian|greek|german|austrian|french|spanish|italian|portuguese|dutch|belgian|swiss|british|irish|"
    r"swedish|norwegian|danish|finnish|berliner|european|uk|us|eu)\b\s*", re.I)
DESCRIPTOR = re.compile(r"\b(?:startup|start-up|scale-?up|spinout|spin-off|company|firm|platform|unicorn|"
                        r"provider|maker|developer)\b", re.I)


def extract_company(title: str) -> str:
    m = MONEY_VERB.search(title)
    head = title[:m.start()] if m else title
    head = re.sub(r"\s+", " ", head).strip(" :-–—,")
    head = re.sub(r"^(?:exclusive|ексклюзив)\s*:\s*", "", head, flags=re.I)
    if ":" in head:  # "Procuros: Berliner Logistik-Startup" -> Procuros
        head = head.split(":")[0].strip()
    head = re.sub(r"^[A-Z][\w\-]*(?:’|')s\s+", "", head)           # "Zurich’s Klarent"
    head = re.sub(r"^[\w\- ]*?-(?:based|founded)\s+", "", head, flags=re.I)
    head = re.sub(r"^profitable\s+", "", head, flags=re.I)
    head = NATIONALITY.sub("", head)
    parts = DESCRIPTOR.split(head)
    if len(parts) > 1 and parts[-1].strip():
        head = parts[-1].strip()                                      # "stablecoin startup Noah" -> Noah
    words = head.split()
    if not words or len(words) > 4 or not words[0][:1].isupper() and not words[0][:1].isdigit():
        return ""
    return " ".join(words)


def classify(title: str, cats: List[str], desc: str, source: str) -> Optional[dict]:
    text = " ".join([title, " ".join(cats), desc[:600]])
    if SKIP_TITLE.search(title) or not MONEY_VERB.search(title):
        return None
    amt = None
    for m in AMOUNT.finditer(title):
        amt = to_eur_millions(m)
        if amt:
            break
    grant = bool(GRANT.search(title))
    if amt is None and not grant and source != "AIN.ua":
        return None
    company = extract_company(title)
    if INVESTOR_WORDS.search(company) and not grant:
        return None  # a fund raising its own fund is an investor, not a client
    low = text.lower()
    country = next((v for k, v in COUNTRY_HINTS.items() if k in low), "")
    if not country and US_HINTS.search(text):
        return None  # USA is a separate track, later
    sectors = [name for name, pat in SECTORS if re.search(pat, low)]
    rnd = ROUND.search(title) or ROUND.search(desc[:400])
    tier = "premium" if (grant and (amt or 0) >= 1) or (amt or 0) >= 10 else "standard"
    return {
        "company": company or "(див. новину)", "amount_eur_m": amt, "round": rnd.group(1) if rnd else "",
        "grant": grant, "country": country, "sectors": sectors,
        "priority": bool(set(sectors) & PRIORITY_SECTORS), "tier": tier,
    }


def parse_feed(xml: str, source: str) -> List[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title = _clean((re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1])
        link = _clean((re.search(r"<link>(.*?)</link>", it, re.S) or [None, ""])[1])
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
        cats = [_clean(c) for c in re.findall(r"<category>(.*?)</category>", it, re.S)]
        desc = _clean((re.search(r"<description>(.*?)</description>", it, re.S) or [None, ""])[1])
        sig = classify(title, cats, desc, source)
        if not sig:
            continue
        try:
            dt = parsedate_to_datetime(pub.group(1)).astimezone(timezone.utc).date().isoformat() if pub else ""
        except (TypeError, ValueError):
            dt = ""
        sig.update(title=title, url=link, source=source, published=dt)
        out.append(sig)
    return out


def li_search(company: str, role: str) -> str:
    from urllib.parse import quote
    return ("https://www.linkedin.com/search/results/people/?keywords="
            + quote(f"{company} {role}") + "&origin=GLOBAL_SEARCH_HEADER")


def run(log: Callable[[str], None], data_dir: Path = Path("data"), out_dir: Path = Path("out")) -> int:
    pool_path = data_dir / "signals_pool.json"
    try:
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        pool = {}
    today = date.today().isoformat()
    new = 0
    for source, url in FEEDS.items():
        r = _get(url)
        if r is None or r.status_code != 200:
            log(f"Signals: {source} -> {getattr(r, 'status_code', 'request failed')}")
            continue
        got = parse_feed(r.text, source)
        for s in got:
            key = s["url"] or s["title"]
            tkey = re.sub(r"\W+", " ", s["company"].lower()).strip() + "|" + str(s["amount_eur_m"])
            if key in pool or any(v.get("_tkey") == tkey and s["company"] != "(див. новину)" for v in pool.values()):
                continue  # same deal reported by two outlets
            s["_tkey"], s["found"] = tkey, today
            co = s["company"] if s["company"] != "(див. новину)" else ""
            s["li_ceo"], s["li_founder"], s["li_coo"] = (li_search(co, "CEO"), li_search(co, "founder"),
                                                         li_search(co, "COO")) if co else ("", "", "")
            pool[key] = s
            new += 1
        log(f"Signals: {source} -> {len(got)} funding item(s)")
    cut_pool = (date.today() - timedelta(days=KEEP_POOL_DAYS)).isoformat()
    pool = {k: v for k, v in pool.items() if v.get("found", today) >= cut_pool}
    pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    cut_out = (date.today() - timedelta(days=KEEP_OUT_DAYS)).isoformat()
    items = sorted((v for v in pool.values() if v["found"] >= cut_out),
                   key=lambda v: (not v["priority"], v["tier"] != "premium", -(v["amount_eur_m"] or 0)))
    clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
    (out_dir / "signals_latest.json").write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Сигнали: хто отримав гроші ({today})", "",
             "| Компанія | Сума, млн € | Раунд | Країна | Сфери | Пріоритет | Новина |", "|---|---|---|---|---|---|---|"]
    for it in clean:
        lines.append(f"| {it['company']} | {it['amount_eur_m'] or ''} | {'грант' if it['grant'] else it['round']} | "
                     f"{it['country']} | {', '.join(it['sectors'])} | "
                     f"{'€200/год' if it['tier'] == 'premium' else ''}{' ★' if it['priority'] else ' спостереження'} | "
                     f"[{it['source']}]({it['url']}) |")
    (out_dir / "signals_latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Signals: {new} new, {len(clean)} in the last {KEEP_OUT_DAYS} days")
    return new
