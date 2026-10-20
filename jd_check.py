"""
jd_check.py - safe first test of Stage A on the real internet.
Reads out/import_latest.json (the postings Agent 1 already found), downloads each ad page, screens it,
prints a table and writes out/jd_check.md. It changes NOTHING else (no seen.json, no email, no tracker).
Run:  cd ~/jobsearch && python3 jd_check.py          (about 1-5 minutes)
      python3 jd_check.py 20                          (only the first 20 rows)
"""
import json
import sys
from pathlib import Path

import jd_fetch

rows = json.loads(Path("out/import_latest.json").read_text(encoding="utf-8"))
arg = sys.argv[1] if len(sys.argv) > 1 else ""
if arg and not arg.isdigit():                       # python3 jd_check.py dev.bg  -> only rows whose url has this text
    rows = [r for r in rows if arg.lower() in (r.get("url") or "").lower()]
limit = int(arg) if arg.isdigit() else len(rows)
posts = [dict(apply=r.get("url") or "UNKNOWN", title=r["role"], hiring_entity=r["company"], source_board=r.get("board", ""))
         for r in rows[:limit]]
print("Checking %d posting(s)..." % len(posts))
CHK = Path("out/check"); CHK.mkdir(parents=True, exist_ok=True)      # own folder: never touch the real out/jd_review.md
jd_fetch.enrich_and_screen(posts, print, CHK)
(CHK / "jd_review.md").replace(Path("out/jd_check.md"))
Path("out/jd_check_texts.json").write_text(json.dumps([{"company": p["hiring_entity"], "role": p["title"], "url": p["apply"], "verdict": p["jd_verdict"], "text": p.get("jd", "")} for p in posts], ensure_ascii=False, indent=1), encoding="utf-8")
probe = Path("out/probe"); probe.mkdir(exist_ok=True)
for n, p in enumerate(posts):                      # raw pages of the postings that gave no text: for debugging
    if p["jd_verdict"] == "nojd" and p.get("_page_html"):
        (probe / ("%02d_%s.html" % (n, "".join(c if c.isalnum() else "_" for c in p["hiring_entity"])[:20]))).write_text(p["_page_html"], encoding="utf-8")
print()
for p in posts:
    hits = [h["label"] for h in p["_jd_res"]["hits"] if h["level"] in ("wall", "ask")]
    print("%-5s %-6s %-22s %-40s %s" % (p["jd_verdict"].upper(), p["jd_src"], p["hiring_entity"][:22], p["title"][:40], "; ".join(hits)[:90]))
print("\nFull list with quotes: out/jd_check.md")
