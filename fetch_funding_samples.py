#!/usr/bin/env python3
"""
fetch_funding_samples.py - one-off helper (12.10). Saves one copy of each candidate
funding / grant news feed into samples/funding/, so Claude can check which feeds exist
and write the parser against real data. Run once on the Mac:  python3 fetch_funding_samples.py
~20 requests, 2 s apart. Changes nothing else.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

FEEDS = {
    # Europe-wide funding news
    "finsmes": "https://www.finsmes.com/feed",
    "eu_startups": "https://www.eu-startups.com/feed/",
    "tech_eu": "https://tech.eu/feed/",
    "sifted": "https://sifted.eu/feed",
    "crunchbase_news": "https://news.crunchbase.com/feed/",
    "silicon_canals": "https://siliconcanals.com/feed/",
    "arctic_startup": "https://arcticstartup.com/feed/",
    "uktn": "https://www.uktech.news/feed",
    "trending_topics": "https://www.trendingtopics.eu/feed/",
    # Bulgaria and Central / Eastern Europe
    "the_recursive": "https://therecursive.com/feed/",
    "itnews_bg": "https://www.investor.bg/rss",
    # Ukraine
    "ain_ua": "https://ain.ua/feed/",
    "dou_news": "https://dou.ua/feed/",
    "usf": "https://usf.com.ua/feed/",
    "brave1": "https://brave1.gov.ua/feed/",
    # Grants (EU)
    "eic_news": "https://eic.ec.europa.eu/news_en",
    # US - later, sampled only to know the format
    "techcrunch_venture": "https://techcrunch.com/category/venture/feed/",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9,uk;q=0.8"}


def main():
    out = Path(__file__).resolve().parent / "samples" / "funding"
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for name, url in FEEDS.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            (out / f"{name}.xml").write_bytes(r.content)
            items = r.text.count("<item>") + r.text.count("<entry>")
            index[name] = {"url": url, "status": r.status_code, "bytes": len(r.content), "items": items}
            print(f"{r.status_code}  {items:>3} items  {name}")
        except Exception as e:
            index[name] = {"url": url, "error": repr(e)[:200]}
            print(f"ERR  {name}: {e!r}"[:120])
        time.sleep(2)
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print("Done. Tell Claude: funding samples ready.")


if __name__ == "__main__":
    main()
