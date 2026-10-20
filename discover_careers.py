#!/usr/bin/env python3
"""
discover_careers.py - one-off helper (12.10). For each company in data/target_companies_ua.json:
  1. downloads its careers page once into samples/careers/<name>.html
  2. looks for a known ATS inside the page (Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
     Teamtailor, Recruitee, Breezy, Personio, Workday, Comeet, Oracle, SuccessFactors, BambooHR, Pinpoint)
  3. checks whether the company has a DOU vacancies RSS feed (jobs.dou.ua/vacancies/<slug>/feeds/)
Writes data/careers_discovery.json. Changes nothing else. Run once on the Mac:
    python3 discover_careers.py
~150 requests, 2 s apart: about 5-6 minutes.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9,uk;q=0.8"}
FINGERPRINTS = [
    ("Greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("Greenhouse", r"boards-api(?:\.eu)?\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)"),
    ("Lever", r"jobs(?:\.eu)?\.lever\.co/([A-Za-z0-9_.-]+)"),
    ("Ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("Workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("SmartRecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("Teamtailor", r"https?://([a-z0-9-]+)\.teamtailor\.com"),
    ("Recruitee", r"https?://([a-z0-9-]+)\.recruitee\.com"),
    ("Breezy HR", r"https?://([a-z0-9-]+)\.breezy\.hr"),
    ("Personio", r"https?://([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("Workday", r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[A-Za-z0-9_-]+)"),
    ("Comeet", r"comeet\.(?:co|com)/jobs/([A-Za-z0-9_-]+/[A-Za-z0-9.]+)"),
    ("Oracle HCM", r"https?://([a-z0-9-]+\.fa\.[a-z0-9.-]+oraclecloud\.com)"),
    ("SuccessFactors", r"(successfactors\.(?:com|eu))"),
    ("BambooHR", r"https?://([a-z0-9-]+)\.bamboohr\.com"),
    ("Pinpoint", r"https?://([a-z0-9-]+)\.pinpointhq\.com"),
    ("DOU", r"jobs\.dou\.ua/companies/([a-z0-9-]+)/"),
]
SKIP_SLUGS = {"embed", "js", "assets", "static", "api", "v1", "jobs", "www"}


def get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    except requests.RequestException as e:
        r = e
    time.sleep(2)
    return r


def main():
    root = Path(__file__).resolve().parent
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "data/target_companies_ua.json"
    targets = json.loads((root / src).read_text(encoding="utf-8"))
    out_name = "data/careers_discovery.json" if src.endswith("_ua.json") else src.replace("target_companies", "discovery")
    out_dir = root / "samples/careers"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for t in targets:
        name, url = t["name"], t["careers_url"]
        rec = {"name": name, "careers_url": url}
        r = get(url)
        if isinstance(r, Exception):
            rec.update(status="error", error=repr(r)[:200])
            html = ""
        else:
            rec.update(status=r.status_code, final_url=r.url, bytes=len(r.content))
            html = r.text
            fname = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") + ".html"
            (out_dir / fname).write_text(html, encoding="utf-8", errors="ignore")
            rec["sample"] = f"samples/careers/{fname}"
        extra = []
        for k, xu in enumerate(t.get("extra_urls", [])):
            xr = get(xu)
            if isinstance(xr, Exception):
                extra.append({"url": xu, "status": "error"})
                continue
            xname = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") + f"_extra{k}.html"
            (out_dir / xname).write_text(xr.text, encoding="utf-8", errors="ignore")
            extra.append({"url": xu, "status": xr.status_code, "final_url": xr.url, "bytes": len(xr.content),
                          "sample": f"samples/careers/{xname}"})
            html += " " + xr.text
        rec["extra"] = extra
        hay = (rec.get("final_url") or url) + " " + html
        found = []
        for ats, pat in FINGERPRINTS:
            for m in re.findall(pat, hay, re.I):
                slug = m if isinstance(m, str) else m[0]
                if slug.lower() not in SKIP_SLUGS and (ats, slug) not in found:
                    found.append((ats, slug))
        rec["ats_found"] = [{"ats": a, "slug": s} for a, s in found[:8]]
        dou = []
        cands = list(dict.fromkeys(t.get("dou_candidates", []) + [s for a, s in found if a == "DOU"]))
        for slug in cands[:4]:
            fr = get(f"https://jobs.dou.ua/vacancies/{slug}/feeds/")
            if not isinstance(fr, Exception) and fr.status_code == 200:
                n = fr.text.count("<item>")
                (out_dir / f"dou_{slug}.xml").write_text(fr.text, encoding="utf-8", errors="ignore")
                dou.append({"slug": slug, "items": n})
                if n:
                    break
        rec["dou_feed"] = dou
        results.append(rec)
        print(f"{str(rec.get('status')):>5}  {name:30}  ATS: {', '.join(a for a, _ in found[:3]) or '-':30}  "
              "DOU: " + (", ".join("%s=%s" % (d["slug"], d["items"]) for d in dou) or "-"))
    (root / out_name).write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    print("Done. Tell Claude: discovery ready.")


if __name__ == "__main__":
    main()
