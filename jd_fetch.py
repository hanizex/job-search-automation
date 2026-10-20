"""
jd_fetch.py - gets the text of each NEW job ad and runs jd_screen on it (Stage A, 13.10.2026).

Called from poll_jobs.py after the daily filters, only for postings that are new today (about 10-60 per day).
Order of sources for one posting:
  1. text already inside the list the ATS returned (Lever, Ashby, Recruitee, Breezy, Workable, Amazon, DOU RSS)
  2. the ATS detail API (Greenhouse, SmartRecruiters, Workday)
  3. the ad page itself (JSON-LD JobPosting first, then the visible text) - DEV.BG, Djinni, DOU, company sites
If nothing works the card gets jd_verdict "nojd" - the code never guesses.
Never raises: a failure here must not stop the daily run. Python 3.9 compatible; uses `requests` like boards.py.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Optional

import requests

import jd_screen

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
TIMEOUT = 20
MAX_FETCH = 150          # network fetches per run (list-embedded texts do not count)
BUDGET_SECONDS = 360     # stop fetching after this many seconds in total
PAUSE = 0.6              # polite pause between fetches

_EMBED_PLAIN = ("descriptionPlain", "additionalPlain")
_EMBED_HTML = ("descriptionHtml", "description", "content", "requirements", "qualifications",
               "basic_qualifications", "preferred_qualifications", "additional", "job_description", "jobDescription")


def embedded_text(job: dict) -> str:
    """Whatever description text the ATS list already carries for this posting."""
    parts = []
    has_plain = bool(isinstance(job.get("descriptionPlain"), str) and job.get("descriptionPlain").strip())
    for k in _EMBED_PLAIN:
        v = job.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    if not has_plain:
        for k in _EMBED_HTML:
            v = job.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v)
    else:  # plain text present: still add qualification lists the plain block may not include
        for k in ("requirements", "qualifications", "basic_qualifications", "preferred_qualifications"):
            v = job.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v)
    lists = job.get("lists")                       # Lever: [{"text": "Requirements", "content": "<li>..."}]
    if isinstance(lists, list):
        for it in lists:
            if isinstance(it, dict):
                parts.append("%s:\n%s" % (it.get("text", ""), it.get("content", "")))
    return "\n\n".join(parts)


def attach_sources(p: dict, ats: str, job: dict, endpoint: str) -> None:
    """Called by normalize_job: remember where this posting's ad text can come from (no network here)."""
    emb = embedded_text(job)
    if emb:
        p["_jd_embedded"] = emb
    a = ats.lower()
    if a.startswith("greenhouse") and job.get("id") and endpoint:
        p["_jd_api"] = ("greenhouse", endpoint.split("?")[0].rstrip("/") + "/%s" % job["id"])
    elif a.startswith("smartrecruiters"):
        cid = (job.get("company") or {}).get("identifier")
        if cid and job.get("id"):
            p["_jd_api"] = ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/%s/postings/%s" % (cid, job["id"]))
    elif a.startswith("workday") and job.get("externalPath"):
        m = re.search(r"(https://[^/]+/wday/cxs/[^/]+/[^/]+)/jobs", endpoint or "")
        if m:
            p["_jd_api"] = ("workday", m.group(1) + job["externalPath"])


LAST = {"status": "", "html": ""}      # why the last fetch failed (shown in jd_src when there is no text)


def _get(url: str, accept: str = "*/*") -> Optional[requests.Response]:
    LAST["status"] = ""
    LAST["html"] = ""
    for attempt in (1, 2):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en,uk;q=0.8"},
                             timeout=TIMEOUT)
            LAST["status"] = "HTTP%s" % r.status_code
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404, 410, 401):
                return None
        except requests.RequestException as e:
            LAST["status"] = type(e).__name__
        time.sleep(1.5)
    return None


def _api_text(kind: str, url: str) -> str:
    r = _get(url, "application/json")
    if r is None:
        return ""
    try:
        d = r.json()
    except ValueError:
        return ""
    if kind == "greenhouse":
        return d.get("content") or ""
    if kind == "smartrecruiters":
        secs = ((d.get("jobAd") or {}).get("sections")) or {}
        order = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
        return "\n\n".join("%s:\n%s" % (k, (secs.get(k) or {}).get("text", "")) for k in order if secs.get(k))
    if kind == "workday":
        return (d.get("jobPostingInfo") or {}).get("jobDescription") or ""
    return ""


_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)


def _find_jobposting(o):
    if isinstance(o, dict):
        t = o.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            return o
        for v in o.values():
            f = _find_jobposting(v)
            if f:
                return f
    elif isinstance(o, list):
        for v in o:
            f = _find_jobposting(v)
            if f:
                return f
    return None


_DESC_DIV = re.compile(r'<div\b[^>]*class="[^"]*(?:job[-_]?description|job[-_]?details?|vacancy[-_]?(?:text|body|description)|'
                       r'posting[-_]?description|description)[^"]*"[^>]*>', re.I)


def _balanced_div(h: str, start: int) -> str:
    depth = 0
    for m in re.finditer(r"(?i)<div\b|</div\s*>", h[start:]):
        depth += -1 if m.group(0).startswith("</") else 1
        if depth == 0:
            return h[start:start + m.end()]
    return h[start:start + 30000]


def page_candidates(html_text: str) -> list:
    """Possible ad texts inside a page, as raw HTML/text pieces."""
    cands = []
    for m in _LD.finditer(html_text):                      # JSON-LD JobPosting (sometimes only a teaser ending with "...")
        try:
            jp = _find_jobposting(json.loads(m.group(1)))
        except ValueError:
            continue
        if jp and isinstance(jp.get("description"), str):
            extra = jp.get("qualifications") or jp.get("skills") or ""
            cands.append(jp["description"] + ("\n\n" + extra if isinstance(extra, str) and extra else ""))
    for m in _DESC_DIV.finditer(html_text):                # <div class="job_description"> ... </div>
        cands.append(_balanced_div(html_text, m.start()))
    for m in re.finditer(r"(?is)<(main|article)[^>]*>(.*?)</\1>", html_text):
        cands.append(m.group(2))
    return cands


def _page_text(url: str) -> str:
    r = _get(url, "text/html,application/xhtml+xml")
    if r is None:
        return ""
    html_text = r.text
    LAST["html"] = html_text
    good = [c for c in page_candidates(html_text) if len(jd_screen.clean_text(c)) >= 300]
    if good:                                               # the longest piece is the real ad, the teaser is shorter
        return max(good, key=lambda c: len(jd_screen.clean_text(c)))
    return re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|aside|form)[^>]*>.*?</\1>", " ", html_text)


def get_text(p: dict, state: dict) -> (str, str):
    """-> (clean text, source label). Respects the fetch budget in `state`."""
    emb = jd_screen.clean_text(p.get("_jd_embedded", ""))
    if len(emb) >= jd_screen.MIN_CHARS:
        return emb, "list"
    if state["fetched"] >= MAX_FETCH or time.time() - state["t0"] > BUDGET_SECONDS:
        state["skipped"] += 1
        return emb, "budget" if not emb else "list-short"
    api = p.get("_jd_api")
    if api:
        state["fetched"] += 1
        txt = jd_screen.clean_text(_api_text(api[0], api[1]))
        time.sleep(PAUSE)
        if len(txt) >= jd_screen.MIN_CHARS:
            return txt, "api"
    url = p.get("apply")
    if url and url != "UNKNOWN" and url.startswith("http"):
        state["fetched"] += 1
        txt = jd_screen.clean_text(_page_text(url))
        p["_page_html"] = LAST.get("html", "")             # kept only for jd_check debugging
        time.sleep(PAUSE)
        if len(txt) >= jd_screen.MIN_CHARS:
            return txt, "page"
    return emb, "none" + ("(%s)" % LAST["status"] if LAST["status"] not in ("", "HTTP200") else "(short)")


def enrich_and_screen(postings: list, log: Callable[[str], None], out_dir: Optional[Path] = None) -> dict:
    """Adds jd, jd_src, jd_verdict, jd_why, jd_hits to every posting. Writes out/jd_review.md when out_dir is given."""
    state = {"fetched": 0, "skipped": 0, "t0": time.time()}
    counts = {"wall": 0, "ask": 0, "ok": 0, "nojd": 0}
    by_src = {}
    for p in postings:
        try:
            txt, src = get_text(p, state)
            res = jd_screen.screen(txt, already_clean=True)
        except Exception as e:                      # never block the run
            log("JD screen failed for %s: %r" % (p.get("apply"), e))
            txt, src, res = "", "error", {"verdict": "nojd", "hits": [], "chars": 0, "ad_lang": ""}
        p["jd"] = txt[:jd_screen.MAX_STORE] if res["verdict"] != "nojd" else ""
        p["jd_src"] = src
        p["jd_verdict"] = res["verdict"]
        p["jd_why"] = jd_screen.why(res)
        p["jd_hits"] = [{"id": h["id"], "level": h["level"]} for h in res["hits"]]
        p["_jd_res"] = res
        counts[res["verdict"]] = counts.get(res["verdict"], 0) + 1
        by_src[src] = by_src.get(src, 0) + 1
    log("JD screen: %d posting(s): wall %d, ask %d, ok %d, no text %d | sources %s | network fetches %d (%d skipped by budget)"
        % (len(postings), counts["wall"], counts["ask"], counts["ok"], counts["nojd"], json.dumps(by_src),
           state["fetched"], state["skipped"]))
    if out_dir is not None:
        try:
            write_review(postings, Path(out_dir) / "jd_review.md")
        except Exception as e:
            log("jd_review.md not written: %r" % (e,))
    return counts


def write_review(postings: list, path: Path) -> None:
    """Short list for Mykola: what the code will skip and why, so wrong skips are caught in the first two weeks."""
    from datetime import date
    lines = ["# JD screen %s" % date.today().isoformat(), ""]
    for verdict, title in (("wall", "Авто-skip (стіна)"), ("ask", "Перевір сам"), ("nojd", "Текст не завантажено")):
        rows = [p for p in postings if p.get("jd_verdict") == verdict]
        lines.append("## %s: %d" % (title, len(rows)))
        for p in rows:
            company = p["hiring_entity"] if p.get("hiring_entity") not in (None, "UNKNOWN") else p.get("source_board", "")
            lines.append("- **%s** — %s — %s" % (company, p.get("title", ""), p.get("apply", "")))
            if verdict != "nojd":
                for h in p["_jd_res"]["hits"]:
                    if h["level"] in ("wall", "ask"):
                        lines.append("    - %s: %s — «%s»" % ("стіна" if h["level"] == "wall" else "перевір", h["label"], h["quote"][:200]))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
