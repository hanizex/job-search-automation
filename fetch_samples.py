#!/usr/bin/env python3
"""
fetch_samples.py - one-off helper (11.10). Downloads ONE copy of each job-board listing page
into samples/, so Claude can read the real page structure and write board parsers.
Run once on the Mac:  python3 fetch_samples.py
It makes ~16 requests, 3 seconds apart, and changes nothing else.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

PAGES = {
    # Bulgaria - home market, office / hybrid in Sofia is fine
    "devbg_pm_all": "https://dev.bg/company/jobs/it-project-management/",
    "devbg_pm_remote": "https://dev.bg/company/jobs/it-project-management/remote/",
    "devbg_pmba_sofia": "https://dev.bg/company/jobs/pm-ba-and-more/sofiya/",
    "devbg_pmba_remote": "https://dev.bg/company/jobs/pm-ba-and-more/remote/",
    "jobsbg_pm": "https://www.jobs.bg/front_job_search.php?keywords%5B%5D=project+manager",
    # Ukraine
    "dou_rss_project": "https://jobs.dou.ua/vacancies/feeds/?category=Project%20Manager",
    "dou_rss_product": "https://jobs.dou.ua/vacancies/feeds/?category=Product%20Manager",
    "dou_html_project_remote": "https://jobs.dou.ua/vacancies/?remote&category=Project%20Manager",
    "djinni_project": "https://djinni.co/jobs/?primary_keyword=Project+Manager",
    "djinni_product": "https://djinni.co/jobs/?primary_keyword=Product+Manager",
    "djinni_delivery": "https://djinni.co/jobs/keyword-delivery_manager/",
    "djinni_rss_project": "https://djinni.co/jobs/rss/?primary_keyword=Project+Manager",
    # Poland - waiting list only, sampled to measure volume
    "justjoin_pm_remote": "https://justjoin.it/job-offers/remote/pm",
    "justjoin_pm_all": "https://justjoin.it/job-offers/all-locations/pm",
    "nofluff_pm_remote": "https://nofluffjobs.com/pl/praca-zdalna/project-manager",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def main():
    out = Path(__file__).resolve().parent / "samples"
    out.mkdir(exist_ok=True)
    index = {}
    for name, url in PAGES.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            ext = "xml" if "rss" in name else "html"
            (out / f"{name}.{ext}").write_bytes(r.content)
            index[name] = {"url": url, "final_url": r.url, "status": r.status_code,
                           "bytes": len(r.content), "type": r.headers.get("content-type", "")}
            print(f"{r.status_code}  {len(r.content):>8} bytes  {name}")
        except Exception as e:
            index[name] = {"url": url, "error": repr(e)}
            print(f"ERR  {name}: {e!r}")
        time.sleep(3)
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print("Done. Tell Claude: samples ready.")


if __name__ == "__main__":
    main()
