"""
demo_offline.py - runs the engine on invented postings, with no network and no accounts.

    python3 demo_offline.py --profile profiles/example_pl_python_dev.json
    python3 demo_offline.py --profile profiles/example_eu_remote_pm.json --out examples/sample_digest_eu_pm.md

It applies the same steps as the daily run: title filter, location filter, second-pass filter (language, off-scope words,
excluded companies, priority), ad screening (wall / ask / ok) and a digest. The postings are in fixtures/mock_postings.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import job_filters
import jd_screen
import poll_jobs
import priorities
import search_profile as profile

HERE = Path(__file__).parent


def run(postings: list) -> dict:
    """-> {"kept": [...], "dropped": [(posting, reason)]} with priority and ad verdict on the kept ones."""
    kept, dropped = [], []
    for p in postings:
        row = dict(p)
        if not poll_jobs.title_matches(row["title"]):
            dropped.append((row, "title does not match your roles"))
            continue
        if not poll_jobs.location_matches(row["location"]):
            dropped.append((row, "location is outside your zones"))
            continue
        verdict, reason = job_filters.classify(row, [])
        if verdict == "drop":
            dropped.append((row, reason))
            continue
        res = jd_screen.screen(row.get("jd", ""))
        row["jd_verdict"], row["jd_why"] = res["verdict"], jd_screen.why(res)
        if res["verdict"] == "wall":
            dropped.append((row, "ad wall: " + row["jd_why"]))
            continue
        kept.append(row)
    kept.sort(key=lambda r: (r["priority"], r["posted_display"] and -int(r["posted_display"].replace("-", ""))))
    return {"kept": kept, "dropped": dropped}


def digest(result: dict, name: str) -> str:
    lines = [f"# Daily digest (invented postings) - profile: {name}", "",
             f"Kept {len(result['kept'])}, dropped {len(result['dropped'])}.", "",
             "| Prio | Company | Role | Location | Ad check | Note |", "|---|---|---|---|---|---|"]
    for r in result["kept"]:
        note = r["jd_why"].replace("|", "/") or "-"
        lines.append(f"| {priorities.label(r['priority'])} | {r['hiring_entity']} | {r['title']} | {r['location']} | {r['jd_verdict']} | {note} |")
    lines += ["", "## Dropped, with the reason", ""]
    for r, reason in result["dropped"]:
        lines.append(f"- {r['hiring_entity']}: {r['title']} ({r['location']}): {reason}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", type=Path, default=None, help="search profile (JSON); default $JSE_PROFILE or ./profile.json")
    ap.add_argument("--out", type=Path, default=None, help="also write the digest to this file")
    args = ap.parse_args(argv)
    try:
        profile.use(args.profile) if args.profile else profile.active()
    except profile.ProfileError as e:
        print(e, file=sys.stderr)
        return 2
    postings = json.loads((HERE / "fixtures" / "mock_postings.json").read_text(encoding="utf-8"))
    text = digest(run(postings), profile.active().get("name") or "unnamed")
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
