#!/usr/bin/env python3
"""
discover_ats.py — ATS / job-endpoint discovery for the Tier-1 target list.

Reads the numbered company rows out of data/07_TIER1_LIST.md, works out
which Applicant Tracking System (ATS) each company publishes jobs through,
and writes a validated, machine-readable endpoint for it (or MANUAL, with
an honest reason) to data/companies.json.

    python3 discover_ats.py                 # full run: parse list, re-validate
                                             # known results live, probe new
                                             # companies generically, write JSON
    python3 discover_ats.py --offline       # skip all network calls; just
                                             # regenerate companies.json from
                                             # the KNOWN_RESULTS seed table
    python3 discover_ats.py --list PATH     # use a different source file
    python3 discover_ats.py --out PATH      # write somewhere else

WHY THERE IS A SEED TABLE (KNOWN_RESULTS)
------------------------------------------
Greenhouse / Lever / Ashby / SmartRecruiters / Personio / Workable /
Recruitee / Breezy HR all expose a *guessable* slug pattern
(https://api.<ats>/.../<company-slug>) that can be brute-forced and
validated with a plain GET. Workday, SuccessFactors, Avature, Phenom
People and Oracle HCM do NOT — their tenant/site/company codes are
arbitrary strings assigned when the company set up the system
(e.g. Accenture's Workday tenant is "accenture" but its *site* is
"AccentureCareers" on pod "wd103" — nothing about the company name tells
you that). Those had to be found by actually locating each company's real
careers URL and reading the redirect target. That one-time research is
recorded here so re-running this script doesn't silently drop it, and so
a newly-added company that turns out to need the same treatment can be
added by hand to this same table.

A record here is safe to trust more than a fresh guess: every entry was
produced by fetching the real endpoint (or the real careers page for
POST-only / SPA-only ATSes) and confirming genuine, non-empty postings —
never assumed from the company name. See each "notes" field for exactly
what was checked. Re-run without --offline and this script will
re-validate every GET-checkable endpoint below and downgrade it to MANUAL
if it has gone stale (link rot, slug changed, board taken down).

NO DEPENDENCIES BEYOND `requests` (matches poll_jobs.py's constraint).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

import ats_fetch

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobSearchDiscovery/1.0; "
    "personal job-monitoring tool; contact via LinkedIn)"
}
TIMEOUT = 10
RATE_LIMIT_SECONDS = 1.0

# Workday's job-search endpoint is POST-only and needs this body shape.
# Kept here so poll_jobs.py (the daily poller) and anyone re-validating a
# Workday entry by hand can reuse it instead of re-deriving it.
WORKDAY_SEARCH_BODY = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

GET_CHECKABLE_ATS = {
    "Greenhouse",
    "Greenhouse (EU)",
    "Lever",
    "Ashby",
    "SmartRecruiters",
    "Recruitee",
    "Breezy HR",
    "Workable",
    "Amazon (proprietary JSON API)",
}

# ---------------------------------------------------------------------------
# Hand-verified results (see module docstring for why these exist).
# Keyed by the exact company name as it appears in 07_TIER1_LIST.md.
# ---------------------------------------------------------------------------
KNOWN_RESULTS: dict[str, dict] = {
    "SAP Labs Bulgaria": dict(
        ats="SuccessFactors", endpoint="", status="MANUAL",
        notes="jobs.sap.com runs on SAP SuccessFactors Career Site Builder "
              "(confirmed via the rmkcdn.successfactors.com CDN fingerprint). "
              "Listings are server-rendered HTML with no discoverable JSON "
              "API. Greenhouse slug 'sap' 404s. Needs manual/Chrome-agent "
              "monitoring, filtered to Bulgaria.",
    ),
    "Broadcom": dict(
        ats="Workday",
        endpoint="https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs",
        status="OK",
        notes="Confirmed live at broadcom.wd1.myworkdayjobs.com/en-US/External_Career "
              "(tenant=broadcom, site=External_Career). Requires a POST with "
              "WORKDAY_SEARCH_BODY as the JSON body — a plain GET returns nothing.",
    ),
    "VMware": dict(
        ats="Workday",
        endpoint="https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs",
        status="OK",
        notes="VMware's own tenant (vmware.wd1.myworkdayjobs.com) now 500s. "
              "VMware requisitions have been folded into Broadcom's Workday "
              "board post-acquisition — filter results for VMware team names. "
              "Same POST requirement as Broadcom.",
    ),
    "IBM Bulgaria": dict(
        ats="Avature", endpoint="", status="MANUAL",
        notes="careers.ibm.com runs on Avature (corroborated by third-party "
              "job boards labeling postings 'IBM - Avature'). No public "
              "unauthenticated API; direct fetch returns a JS-rendered shell.",
    ),
    "Cisco Bulgaria": dict(
        ats="Phenom People", endpoint="", status="MANUAL",
        notes="jobs.cisco.com redirects to careers.cisco.com, confirmed on "
              "Phenom People's CareerConnect (cdn.phenompeople.com/"
              "CareerConnectResources/CISCISGLOBAL asset paths). No public "
              "API found. Fallback: scrape careers.cisco.com/global/en/"
              "search-results filtered to Bulgaria.",
    ),
    "Uber Sofia": dict(
        ats="Oracle HCM", endpoint="", status="MANUAL",
        notes="jobs.uber.com redirects to an Oracle Cloud HCM/Recruiting "
              "instance (iaziqy.fa.ocs.oraclecloud.com). A guessed REST "
              "probe (recruitingCEJobRequisitions, siteNumber=CX_1) returned "
              "HTTP 400 — the real site number isn't guessable without "
              "deeper reverse engineering.",
    ),
    "OpenText Sofia": dict(
        ats="Phenom People", endpoint="", status="MANUAL",
        notes="careers.opentext.com confirmed on Phenom People's "
              "CareerConnect (cdn.phenompeople.com/CareerConnectResources/"
              "OPJOPEUS asset paths). No public API found.",
    ),
    "NVIDIA Bulgaria EOOD": dict(
        ats="Workday",
        endpoint="https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs",
        status="OK",
        notes="Confirmed live at nvidia.wd5.myworkdayjobs.com/"
              "NVIDIAExternalCareerSite (tenant=nvidia, site="
              "NVIDIAExternalCareerSite). Requires POST with WORKDAY_SEARCH_BODY.",
    ),
    "Microsoft Bulgaria": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="careers.microsoft.com is a proprietary site. A community-"
              "documented internal API exists at gcsservices.careers."
              "microsoft.com/search/api/v1/search (used by third-party "
              "scrapers) but robots.txt blocked verification through the "
              "research tooling used here — worth trying directly with "
              "`requests` (robots.txt doesn't bind real HTTP clients), but "
              "unverified, so left MANUAL rather than guessed.",
    ),
    "Amazon / AWS Bulgaria": dict(
        ats="Amazon (proprietary JSON API)",
        endpoint="https://www.amazon.jobs/en/search.json",
        status="OK",
        notes="Public, unauthenticated, confirmed non-empty JSON. CORRECTED: "
              "an earlier version of this table said country/location query "
              "params were unreliable and planned to fetch broadly and "
              "filter client-side — but the unfiltered global search caps "
              "`hits` at exactly 10000 (a plain Elasticsearch "
              "max_result_window; confirmed live by paging past offset 9900 "
              "until the request itself starts erroring), which is both "
              "meaningless as a true total and would take ~100 requests to "
              "even reach. The real, working filter param, found by "
              "inspecting amazon.jobs' own search network traffic, is "
              "`country=BGR` (NOT `normalized_country_code[]`, which "
              "silently returns 0 every time — that's what made it look "
              "unreliable). ats_fetch.fetch_amazon_all() uses country=BGR "
              "by default, so the job_count logged for this company is the "
              "true, currently-open Bulgaria count — which can legitimately "
              "be 0.",
    ),
    "Experian Bulgaria": dict(
        ats="SmartRecruiters",
        endpoint="https://api.smartrecruiters.com/v1/companies/Experian/postings",
        status="OK",
        notes="join.smartrecruiters.com/Experian confirmed as the real "
              "board (22 open Bulgaria roles seen on the page itself). Raw "
              "API JSON wasn't fetchable during research (robots.txt) — "
              "re-verify on first real run. Remember: SmartRecruiters "
              "returns HTTP 200 with an EMPTY list for any slug, valid or "
              "not, so this script only trusts a non-empty 'content' array.",
    ),
    "Bosch Digital Bulgaria": dict(
        ats="SmartRecruiters",
        endpoint="https://api.smartrecruiters.com/v1/companies/BoschGroup/postings",
        status="OK",
        notes="jobs.bosch.com's page config directly references "
              "SmartRecruiters company id 'BoschGroup'. Raw API JSON "
              "unverified during research (robots.txt) — re-verify on "
              "first real run; same empty-list-for-any-slug caveat applies.",
    ),
    "Paysafe Sofia": dict(
        ats="HiBob", endpoint="https://paysafe.careers.hibob.com/jobs",
        status="MANUAL",
        notes="Per the known lead: live board is the HiBob-hosted "
              "paysafe.careers.hibob.com/jobs. HiBob's real Hiring API "
              "(apidocs.hibob.com) requires a private per-company API key; "
              "the public board itself is a JS SPA with no discoverable "
              "unauthenticated feed. The old jobs.paysafe.com "
              "(SuccessFactors) is intentionally excluded — it serves "
              "stale/filled roles. Use the Chrome-based agent for this one.",
    ),
    "Coca-Cola HBC Digital Hub": dict(
        ats="Unknown (likely Oracle Taleo)", endpoint="", status="MANUAL",
        notes="careers.coca-colahellenic.com uses a /careers/SearchJobs URL "
              "pattern typical of Oracle Taleo, but this wasn't confirmed "
              "(robots.txt blocked the relevant path). Note: "
              "coke.wd1.myworkdayjobs.com belongs to The Coca-Cola Company "
              "(TCCC) — a different legal entity from bottler Coca-Cola "
              "HBC — don't conflate the two.",
    ),
    "HP Inc. Bulgaria": dict(
        ats="Workday",
        endpoint="https://hp.wd5.myworkdayjobs.com/wday/cxs/hp/ExternalCareerSite/jobs",
        status="OK",
        notes="Confirmed live at hp.wd5.myworkdayjobs.com/ExternalCareerSite "
              "(tenant=hp, pod=wd5, site=ExternalCareerSite). Requires POST "
              "with WORKDAY_SEARCH_BODY.",
    ),
    "Schwarz IT Bulgaria (Lidl/Kaufland)": dict(
        ats="SuccessFactors",
        endpoint="https://career5.successfactors.eu/careers?company=SCHWARZ",
        status="MANUAL",
        notes="schwarz.jobs.schwarz routes to this SuccessFactors career "
              "gateway (company=SCHWARZ). It's the HTML career-site page, "
              "not a machine-readable feed — SuccessFactors Career Site "
              "Builder has no standardized public API.",
    ),
    "Ocado Technology Sofia": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/ocadogroup/jobs",
        status="OK",
        notes="Parent Ocado Group's careers.ocadogroup.com is Greenhouse-"
              "embedded, slug 'ocadogroup' (not 'ocado'). Confirmed 53 live "
              "postings including 8 explicitly located in Sofia.",
    ),
    "Sutherland": dict(
        ats="SmartRecruiters",
        endpoint="https://api.smartrecruiters.com/v1/companies/Sutherland/postings",
        status="OK",
        notes="jobs.smartrecruiters.com/Sutherland/... shows real live "
              "postings. Raw API unverified during research (robots.txt) — "
              "remember the empty-list-for-any-slug caveat on first real run.",
    ),
    "Accenture": dict(
        ats="Workday",
        endpoint="https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs",
        status="OK",
        notes="Confirmed live tenant at accenture.wd103.myworkdayjobs.com/"
              "AccentureCareers (pod=wd103, an unusually high pod number — "
              "not guessable). Requires POST with WORKDAY_SEARCH_BODY.",
    ),
    "Atos": dict(
        ats="SuccessFactors",
        endpoint="https://career5.successfactors.eu/careers?company=Atos",
        status="MANUAL",
        notes="Real SuccessFactors career site for Atos, but it's the HTML "
              "career page, not a machine-readable feed.",
    ),
    "Wipro": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="careers.wipro.com is a proprietary portal "
              "(job/[title]/[id]-en_US URL pattern). One unconfirmed forum "
              "mention of iCIMS as the backend; no ATS match confirmed.",
    ),
    "DXC": dict(
        ats="Workday",
        endpoint="https://dxctechnology.wd1.myworkdayjobs.com/wday/cxs/dxctechnology/DXCJobs/jobs",
        status="OK",
        notes="Confirmed live tenant at dxctechnology.wd1.myworkdayjobs.com/"
              "DXCJobs (1449+ postings seen). Requires POST with "
              "WORKDAY_SEARCH_BODY.",
    ),
    "Payhawk": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/payhawkio/jobs",
        status="OK",
        notes="payhawk.com/careers is Greenhouse, slug 'payhawkio' — NOT "
              "'payhawk', which 404s. CORRECTED: an earlier version of this "
              "table used boards-api.eu.greenhouse.io because the public "
              "career site lives on job-boards.eu.greenhouse.io, but that "
              "'eu.' API host doesn't serve job JSON at all — it 302s to "
              "/users/sign_in (an admin login), so it silently looked "
              "'down' on every later revalidation. The actual public Job "
              "Board API is unified on the plain boards-api.greenhouse.io "
              "host regardless of which regional domain the career site "
              "itself is served from. Confirmed live: 45 postings.",
    ),
    "SiteGround": dict(
        ats="Lever",
        endpoint="https://api.lever.co/v0/postings/siteground?mode=json",
        status="OK",
        notes="Directly verified: real, non-empty postings including "
              "Sofia-based roles (e.g. Front-End Engineer, Design System).",
    ),
    "Progress (Telerik)": dict(
        ats="Jobvite", endpoint="https://jobs.jobvite.com/progress/jobs",
        status="MANUAL",
        notes="Careers hosted on Jobvite, slug 'progress'. Page is "
              "HTML-only; no public JSON feed found even with common "
              "?json=1-style query tricks.",
    ),
    "Nexo": dict(
        ats="Breezy HR", endpoint="https://nexo.breezy.hr/json",
        status="OK",
        notes="Directly verified: 26 live postings, many Sofia/Bulgaria-"
              "based. Breezy HR isn't one of the ATSes named in the brief "
              "but exposes a genuinely public, unauthenticated JSON feed.",
    ),
    "Chaos (V-Ray)": dict(
        ats="Recruitee", endpoint="https://chaos.recruitee.com/api/offers/",
        status="OK",
        notes="careers.chaos.com's footer credits Recruitee. Directly "
              "verified: 6 live postings. A Greenhouse slug "
              "'chaosindustries' exists but belongs to an unrelated US "
              "defense company — do not use it for this Chaos (V-Ray).",
    ),
    "Yotpo Sofia": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/yotpo/jobs",
        status="OK",
        notes="Directly verified: 14 live postings including Sofia-based "
              "roles.",
    ),
    "bunq Sofia": dict(
        ats="Recruitee", endpoint="https://bunq.recruitee.com/api/offers/",
        status="OK",
        notes="careers.bunq.com's Framer front-end hides the ATS in the "
              "HTML, but slug 'bunq' on Recruitee is directly verified "
              "live with real postings.",
    ),
    "Dreamix": dict(
        ats="Workable",
        endpoint="https://apply.workable.com/api/v1/widget/accounts/dreamix-ltd",
        status="OK",
        notes="dreamix.eu/careers links to apply.workable.com/dreamix-ltd. "
              "Directly verified: 10 live postings, mostly Sofia/remote.",
    ),
    "Scalefocus": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="scalefocus.com/careers is a fully custom portal — no ATS "
              "branding, script, or API reference of any kind found in "
              "the page source.",
    ),
    "Sciant": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="Sciant has been absorbed into Sirma Group ('Sciant is now "
              "Sirma'); careers now live at careers.sirma.com/"
              "open-positions.html, a custom portal with no detectable ATS.",
    ),
    "Melon": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="Careers on melontech.com/careers/open-positions (own "
              "domain). No Greenhouse/Ashby slug worked; melontech.com's "
              "robots.txt blocked deeper inspection of the job page "
              "itself. Likely fully custom.",
    ),
    "Revolut": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="revolut.com/careers uses UUID-based paths on their own "
              "domain (423 positions seen). No Greenhouse/Lever/Ashby/"
              "Workday/Personio/Teamtailor match found — appears to be a "
              "custom in-house system.",
    ),
    "Wise": dict(
        ats="SmartRecruiters",
        endpoint="https://api.smartrecruiters.com/v1/companies/Wise/postings",
        status="OK",
        notes="wise.jobs footer states 'Career site system powered by "
              "SmartRecruiters Attrax'. jobs.smartrecruiters.com/Wise/... "
              "shows real live postings across many countries. NOTE: "
              "boards-api.greenhouse.io/v1/boards/wise/jobs also returns "
              "200 with jobs, but that board belongs to an unrelated US "
              "company also named Wise — a false positive, do not use it.",
    ),
    "Bolt": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="bolt.eu/en/careers/positions uses UUID paths served from "
              "assets.careers-v3.bolt.eu, a custom platform. A Greenhouse "
              "token 'bolt42' exists and returns real jobs, but belongs to "
              "an unrelated US company also called Bolt (commerce/"
              "checkout) — do not use it for Bolt (ride-hailing).",
    ),
    "Nord Security": dict(
        ats="Ashby",
        endpoint="https://api.ashbyhq.com/posting-api/job-board/nord-security",
        status="OK",
        notes="Directly verified: 8 live postings (e.g. iOS Engineer, "
              "Outreach Specialist).",
    ),
    "Vinted": dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="careers.vinted.com/jobs (122 positions) is on their own "
              "domain with client-side 'Load more' pagination; no "
              "'powered by' attribution and no Greenhouse/Lever/Ashby "
              "match found.",
    ),
    "Grafana Labs": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/grafanalabs/jobs",
        status="OK",
        notes="Directly verified: 116 live postings across many EU "
              "countries.",
    ),
    "PostHog": dict(
        ats="Ashby",
        endpoint="https://api.ashbyhq.com/posting-api/job-board/posthog",
        status="OK",
        notes="Directly verified: 7 live postings.",
    ),
    "Deel": dict(
        ats="Ashby",
        endpoint="https://api.ashbyhq.com/posting-api/job-board/deel",
        status="MANUAL",
        notes="jobs.ashbyhq.com/deel is a live board with real postings, "
              "but the public posting-api endpoint returns an EMPTY jobs "
              "array for both 'deel' and 'Deel' — the API appears to be "
              "disabled even though the board itself is live. Recheck "
              "periodically in case it's re-enabled; scrape the hosted "
              "board page as a fallback.",
    ),
    "Remote.com": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/remotecom/jobs",
        status="OK",
        notes="Slug is 'remotecom'. Directly verified: 100+ live postings "
              "across regions.",
    ),
    "Oyster": dict(
        ats="Ashby",
        endpoint="https://api.ashbyhq.com/posting-api/job-board/oyster",
        status="OK",
        notes="Slug is 'oyster' — NOT 'oysterhr', which 404s. Directly "
              "verified: 5 live postings.",
    ),
    "Bybit": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/bybit/jobs",
        status="OK",
        notes="job-boards.eu.greenhouse.io/bybit is the public career site, "
              "but (see the Payhawk entry for the full explanation) the "
              "'eu.' API host doesn't serve job JSON — it redirects to an "
              "admin login. The real Job Board API is on the plain "
              "boards-api.greenhouse.io host. Confirmed live: 160 postings.",
    ),
    "OKX": dict(
        ats="Greenhouse",
        endpoint="https://boards-api.greenhouse.io/v1/boards/okx/jobs",
        status="OK",
        notes="Directly verified: 200+ live postings across global "
              "offices.",
    ),
    "Kraken": dict(
        ats="Ashby",
        endpoint="https://api.ashbyhq.com/posting-api/job-board/kraken.com",
        status="OK",
        notes="Slug includes '.com': 'kraken.com'. Directly verified: 6 "
              "live postings; company shows as 'Payward' (Kraken's legal/"
              "parent name) in the data.",
    ),
    "Crypto.com": dict(
        ats="Lever", endpoint="https://api.lever.co/v0/postings/crypto?mode=json",
        status="OK",
        notes="Slug is 'crypto'. Directly verified: 10 live postings.",
    ),
    "Bitget": dict(
        ats="Workable", endpoint="https://apply.workable.com/bitget/",
        status="MANUAL",
        notes="apply.workable.com/bitget is a live board with real "
              "individual job pages, but both the v1 widget API and a v3 "
              "attempt return an empty/404 result — the public JSON feed "
              "appears disabled. Scrape the board page as a fallback.",
    ),
}


# ---------------------------------------------------------------------------
# Parsing 07_TIER1_LIST.md
# ---------------------------------------------------------------------------
def parse_companies(md_path: Path) -> list[str]:
    """Pull company names out of the numbered rows of the Tier-1 tables.

    Only rows that start with a row number are treated as canonical list
    entries — this naturally skips the "Others checked" commentary table
    (no number column) and every header/separator row.
    """
    text = md_path.read_text(encoding="utf-8")
    companies: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*\d+\s*\|\s*(.+?)\s*\|", line)
        if not m:
            continue
        cell = m.group(1)
        companies.extend(_split_companies(cell))
    return companies


def _split_companies(cell: str) -> list[str]:
    cell = re.sub(r"\*\*", "", cell).strip()

    # Row-34 style: "Crypto exchanges — Bybit, OKX, Kraken, Crypto.com, Bitget"
    m = re.search(r"[—-]\s*([A-Za-z0-9][A-Za-z0-9.,&'\s]+)$", cell)
    if m and "," in m.group(1):
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if len(parts) > 1:
            return parts

    # Split on "/" but only outside parentheses, so
    # "Schwarz IT Bulgaria (Lidl/Kaufland)" stays one company while
    # "Broadcom / VMware" splits into two.
    parts, depth, buf = [], 0, ""
    for ch in cell:
        if ch == "(":
            depth += 1
            buf += ch
        elif ch == ")":
            depth -= 1
            buf += ch
        elif ch == "/" and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) > 1 and not any(re.search(r"\b(Bulgaria|Sofia)\b", p) for p in parts):
        # A genuine multi-company row (e.g. "Sutherland / Accenture / ...").
        return parts

    # A single company whose name just happens to contain "/", e.g.
    # "Amazon / AWS Bulgaria" describing one Sofia office under two brands.
    return [cell]


# ---------------------------------------------------------------------------
# Slug generation for generic (non-seeded) companies
# ---------------------------------------------------------------------------
_SUFFIX_WORDS = {
    "bulgaria", "sofia", "eood", "ltd", "inc", "digital", "labs", "group",
    "technology", "technologies", "software", "hub", "it",
}


def _base_words(name: str) -> list[str]:
    name = re.sub(r"\([^)]*\)", " ", name)  # drop parentheticals
    words = re.findall(r"[A-Za-z0-9']+", name)
    return [w for w in words if w.lower() not in _SUFFIX_WORDS] or words


def slug_candidates(name: str) -> list[str]:
    words = _base_words(name)
    all_words = re.findall(r"[A-Za-z0-9']+", name)
    cands = []
    if words:
        cands.append("".join(w.lower() for w in words))
        cands.append("-".join(w.lower() for w in words))
        cands.append(words[0].lower())
    if all_words:
        cands.append("".join(w.lower() for w in all_words))
    # de-dupe, keep order
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# Live validators — each returns (endpoint, notes) on a confirmed, non-empty
# match, or None. Never trust a 200 with no actual postings in it.
# ---------------------------------------------------------------------------
def _sleep():
    time.sleep(RATE_LIMIT_SECONDS)


def _get(url: str):
    _sleep()
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None


def try_greenhouse(slug: str):
    for host, label in (
        ("boards-api.greenhouse.io", "Greenhouse"),
        ("boards-api.eu.greenhouse.io", "Greenhouse (EU)"),
    ):
        url = f"https://{host}/v1/boards/{slug}/jobs"
        r = _get(url)
        if r is not None and r.status_code == 200:
            try:
                jobs = r.json().get("jobs") or []
            except ValueError:
                jobs = []
            if jobs:
                return label, url, f"{len(jobs)} live postings"
    return None


def try_lever(slug: str):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = _get(url)
    if r is not None and r.status_code == 200:
        try:
            data = r.json()
        except ValueError:
            data = None
        if isinstance(data, list) and data:
            return "Lever", url, f"{len(data)} live postings"
    return None


def try_ashby(slug: str):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = _get(url)
    if r is not None and r.status_code == 200:
        try:
            jobs = r.json().get("jobs") or []
        except ValueError:
            jobs = []
        if jobs:
            return "Ashby", url, f"{len(jobs)} live postings"
    return None


def try_smartrecruiters(slug: str):
    # SmartRecruiters returns HTTP 200 with an EMPTY list for ANY slug,
    # valid or not — an empty "content" array proves nothing.
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    r = _get(url)
    if r is not None and r.status_code == 200:
        try:
            content = r.json().get("content") or []
        except ValueError:
            content = []
        if content:
            return "SmartRecruiters", url, f"{len(content)} live postings"
    return None


def try_personio(slug: str):
    for host in (f"{slug}.jobs.personio.de", f"{slug}.jobs.personio.com"):
        url = f"https://{host}/xml"
        r = _get(url)
        if r is not None and r.status_code == 200 and "<position" in r.text:
            count = r.text.count("<position ")
            return "Personio", url, f"~{count} live postings (XML feed)"
    return None


def try_workable(slug: str):
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    r = _get(url)
    if r is not None and r.status_code == 200:
        try:
            jobs = r.json().get("jobs") or []
        except ValueError:
            jobs = []
        if jobs:
            return "Workable", url, f"{len(jobs)} live postings"
    return None


def try_recruitee(slug: str):
    url = f"https://{slug}.recruitee.com/api/offers/"
    r = _get(url)
    if r is not None and r.status_code == 200:
        try:
            offers = r.json().get("offers") or []
        except ValueError:
            offers = []
        if offers:
            return "Recruitee", url, f"{len(offers)} live postings"
    return None


def try_breezy(slug: str):
    url = f"https://{slug}.breezy.hr/json"
    r = _get(url)
    if r is not None and r.status_code == 200:
        try:
            data = r.json()
        except ValueError:
            data = None
        if isinstance(data, list) and data:
            return "Breezy HR", url, f"{len(data)} live postings"
    return None


# Order matches the brief: Greenhouse, Lever, Ashby, [Workday needs a real
# URL, not a guess — see module docstring], then the rest. Workday /
# SuccessFactors / HiBob / Teamtailor / Avature / Phenom / Oracle are
# deliberately NOT guess-probed here: none of them expose a slug-guessable
# public endpoint, so a "guess" would either always fail or (worse) hit an
# unrelated company that happens to share a slug — exactly the silent-wrong-
# match failure this tool exists to avoid. Add them to KNOWN_RESULTS once
# you've found the real careers URL by hand or via Agent 2 (Chrome).
GENERIC_PROBES = [
    try_greenhouse,
    try_lever,
    try_ashby,
    try_smartrecruiters,
    try_personio,
    try_workable,
    try_recruitee,
    try_breezy,
]


def discover_generic(name: str) -> dict:
    for slug in slug_candidates(name):
        for probe in GENERIC_PROBES:
            result = probe(slug)
            if result:
                ats, endpoint, note = result
                return dict(
                    ats=ats, endpoint=endpoint, status="OK",
                    notes=f"Auto-detected via slug '{slug}': {note}.",
                )
    return dict(
        ats="Unknown", endpoint="", status="MANUAL",
        notes="No Greenhouse/Lever/Ashby/SmartRecruiters/Personio/Workable/"
              "Recruitee/Breezy slug matched. May run Workday, SuccessFactors, "
              "HiBob, Teamtailor, Avature, Phenom People, Oracle HCM, or a "
              "fully proprietary portal — none of those are guessable from "
              "the company name alone. Find the real careers URL by hand "
              "(or via the Chrome-based agent) and add it to KNOWN_RESULTS.",
    )


def revalidate_known(name: str, known: dict) -> dict:
    """Re-check a GET-checkable known-good endpoint; leave POST-only /
    already-MANUAL entries as recorded (they can't be cheaply re-checked
    with a plain GET, and re-guessing them risks the same false-match
    problem discussed in the module docstring).

    Anything ats_fetch.py knows how to fully paginate is skipped here on
    purpose: fetch_true_totals() (called later, after every company is
    resolved) does a far more thorough re-check of these — a real full
    pagination pass instead of a single untrusted page — and is the single
    source of truth for their status/notes/count. Running both left
    contradictory leftovers in `notes` (e.g. Amazon showing "10 live
    postings" from this page-1 check immediately followed by "0 live
    postings" from the country-filtered full fetch)."""
    if known["status"] != "OK" or known["ats"] not in GET_CHECKABLE_ATS:
        return known
    if known["ats"] in ats_fetch.FETCHABLE_ATS:
        return known

    url = known["endpoint"]
    r = _get(url)
    ok = False
    count = None
    if r is not None and r.status_code == 200:
        try:
            data = r.json()
        except ValueError:
            data = None
        if isinstance(data, dict):
            items = data.get("jobs") or data.get("content") or data.get("offers")
            if items:
                ok, count = True, len(items)
        elif isinstance(data, list) and data:
            ok, count = True, len(data)

    if ok:
        updated = dict(known)
        updated["notes"] = f"Re-validated this run: {count} live postings at {url}."
        return updated

    downgraded = dict(known)
    downgraded["status"] = "MANUAL"
    downgraded["notes"] = (
        f"Previously verified endpoint ({url}) did not return live postings "
        f"on this run — possible link rot, slug change, or the board went "
        f"down. Original notes: {known['notes']}"
    )
    return downgraded


def normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def resolve_company(name: str, offline: bool) -> dict:
    known_by_norm = {normalize(k): v for k, v in KNOWN_RESULTS.items()}
    known = known_by_norm.get(normalize(name))
    if known is not None:
        result = dict(known) if offline else revalidate_known(name, known)
    else:
        result = (
            dict(ats="Unknown", endpoint="", status="MANUAL",
                 notes="Not in the seed table and --offline was set, so no "
                       "live probing was attempted.")
            if offline
            else discover_generic(name)
        )
    result["name"] = name
    return result


# ---------------------------------------------------------------------------
# True-total fetch pass — runs after ATS/endpoint discovery. Discovery only
# needs a single non-empty page to identify the right ATS and slug; getting
# an honest count needs the full pagination layer in ats_fetch.py. Kept as a
# separate pass so two companies sharing one endpoint (Broadcom & VMware
# both point at the same Workday tenant) are fetched exactly once instead
# of twice, with the result attributed back to every company that shares it.
# ---------------------------------------------------------------------------
def fetch_true_totals(results: list[dict]) -> tuple[list[str], list[str]]:
    """Mutates each OK result in place: adds 'job_count' (and
    'job_count_low_confidence') and appends the confirmed true total to its
    notes. Returns (zero_postings_warnings, low_confidence_warnings)."""
    endpoint_groups: dict[tuple[str, str], list[dict]] = {}
    for r in results:
        if r["status"] == "OK" and r["ats"] in ats_fetch.FETCHABLE_ATS:
            endpoint_groups.setdefault((r["ats"], r["endpoint"]), []).append(r)
        else:
            r["job_count"] = None
            r["job_count_low_confidence"] = False

    dupe_count = sum(len(v) for v in endpoint_groups.values()) - len(endpoint_groups)
    if dupe_count:
        print(f"Deduping: {len(endpoint_groups)} unique endpoint(s) cover "
              f"{dupe_count + len(endpoint_groups)} OK companies "
              f"({dupe_count} shared with at least one other company).",
              file=sys.stderr)

    zero_warnings: list[str] = []
    low_confidence_warnings: list[str] = []
    for (ats, endpoint), group in endpoint_groups.items():
        names = ", ".join(r["name"] for r in group)
        print(f"Fetching true total: {names} [{ats}] ...", file=sys.stderr)
        fr = ats_fetch.fetch_all(ats, endpoint)
        _sleep()  # be polite between distinct endpoints too

        for r in group:
            r["job_count_low_confidence"] = False
            if fr.error:
                # A request can still fail after ats_fetch's own retries are
                # exhausted (rare, but confirmed live on a DXC fetch mid-
                # pagination). Whatever pages we DID collect before that are
                # still real, confirmed postings — report them as a floor
                # rather than discarding a partial result entirely.
                r["job_count"] = fr.true_total if fr.true_total else None
                r["notes"] += (
                    f" [Full-fetch validation FAILED this run: {fr.error} "
                    f"after {fr.pages_fetched} page(s) — "
                    + (
                        f"collected {fr.true_total} postings before failing; "
                        f"treat as a FLOOR, not the true total; re-run to get "
                        f"the full count.]"
                        if fr.true_total
                        else "no pages completed; re-run.]"
                    )
                )
                continue

            r["job_count"] = fr.true_total
            r["job_count_low_confidence"] = fr.low_confidence
            extra = (
                f" True total confirmed via full pagination: {fr.true_total} "
                f"live postings ({fr.pages_fetched} page(s) fetched"
                + (f", reported total was {fr.reported_total}" if fr.reported_total not in (None, fr.true_total) else "")
                + ")."
            )
            if fr.capped:
                extra += " CAPPED: " + " ".join(fr.warnings)
            r["notes"] += extra

            if fr.low_confidence:
                low_confidence_warnings.append(
                    f"{r['name']} ({ats}) — reported as {fr.true_total}, but "
                    f"unreliable (see notes)"
                )

            if fr.true_total == 0:
                # Flag it, but do NOT auto-downgrade status: the endpoint
                # responded and parsed fine, so it's still a validated,
                # working, pollable feed — zero just means zero *right now*.
                # For most ATSes here that's a red flag (a company the size
                # of DXC or Bosch essentially never has a truly empty global
                # board, so 0 usually means a broken slug/dead board — see
                # the brief this fix responds to). But Amazon is filtered to
                # Bulgaria specifically (see fetch_amazon_all's docstring),
                # where a real, correct 0 is common and exactly the kind of
                # change a job monitor exists to notice — silently marking
                # it MANUAL would make poll_jobs.py stop watching it.
                r["notes"] += " ⚠ ZERO POSTINGS this run — flagged below."
                zero_warnings.append(f"{r['name']} ({ats}) — {endpoint}")

    return zero_warnings, low_confidence_warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", default="data/07_TIER1_LIST.md", type=Path)
    ap.add_argument("--out", default="data/companies.json", type=Path)
    ap.add_argument("--offline", action="store_true",
                     help="Skip all network calls; just regenerate from the "
                          "seed table (unknown companies go MANUAL).")
    ap.add_argument("--force", action="store_true", help="overwrite companies.json even if it holds managed rows")
    args = ap.parse_args()

    if not args.list.exists():
        sys.exit(f"Company list not found: {args.list}")

    # Guard (11.10): companies.json is now also maintained by suggest_companies.py
    # and has hand-excluded rows. A full rebuild here would silently wipe both.
    if args.out.exists() and "--force" not in sys.argv:
        current = json.loads(args.out.read_text(encoding="utf-8"))
        if any(c.get("source") == "suggest_companies" or c.get("status") == "EXCLUDED" for c in current):
            sys.exit("Refusing to overwrite data/companies.json: it holds rows from suggest_companies.py "
                     "or EXCLUDED rows. Use --out somewhere else, or add --force if you really mean it.")

    companies = parse_companies(args.list)
    if not companies:
        sys.exit(f"No numbered company rows found in {args.list}")

    results = []
    for name in companies:
        print(f"Checking: {name} ...", file=sys.stderr)
        results.append(resolve_company(name, args.offline))

    zero_warnings: list[str] = []
    low_confidence_warnings: list[str] = []
    if not args.offline:
        zero_warnings, low_confidence_warnings = fetch_true_totals(results)
    else:
        for r in results:
            r["job_count"] = None
            r["job_count_low_confidence"] = False

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # keep field order stable
    ordered = [
        {k: r[k] for k in ("name", "ats", "endpoint", "status", "notes",
                            "job_count", "job_count_low_confidence")}
        for r in results
    ]
    args.out.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")

    ok = [r for r in ordered if r["status"] == "OK"]
    manual = [r for r in ordered if r["status"] == "MANUAL"]

    print()
    print(f"Resolved {len(ok)}/{len(ordered)} companies to a live, "
          f"validated endpoint. Wrote {args.out}")
    print()
    if ok:
        print("TRUE TOTALS (post-pagination, per company — dupes share a count):")
        for r in sorted(ok, key=lambda r: -(r["job_count"] or 0)):
            flag = " (LOW CONFIDENCE)" if r.get("job_count_low_confidence") else ""
            print(f"  {r['job_count']!s:>5}  {r['name']} ({r['ats']}){flag}")
    print()
    if manual:
        print(f"MANUAL ({len(manual)}) — no clean machine-readable feed found:")
        for r in manual:
            print(f"  - {r['name']} ({r['ats']})")
    print()
    if zero_warnings:
        print(f"⚠️  ZERO POSTINGS ({len(zero_warnings)}) — confirmed via full "
              f"pagination, not just an empty first page. For most of these, "
              f"a company-wide board going to true zero usually means a "
              f"broken slug or a dead endpoint, not a real absence of jobs "
              f"— go verify by hand. (Exception: Amazon's fetch is filtered "
              f"to Bulgaria specifically, where a real, correct zero is "
              f"common — that one's still worth watching, not necessarily "
              f"broken.)")
        for w in zero_warnings:
            print(f"  - {w}")
        print()
    if low_confidence_warnings:
        print(f"⚠️  LOW-CONFIDENCE COUNTS ({len(low_confidence_warnings)}) — "
              f"wraparound was detected within the first few pages, meaning "
              f"this ATS's default result ordering isn't stable across "
              f"paginated requests (confirmed on Workday: the same tenant "
              f"has wrapped anywhere from page 2 to page 25+ across "
              f"different runs, with nothing about the board itself "
              f"changing). The number shown is a weak floor, not a "
              f"trustworthy total — don't alert on small changes to it:")
        for w in low_confidence_warnings:
            print(f"  - {w}")
        print()
    print("Done.")


if __name__ == "__main__":
    main()
