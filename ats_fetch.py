#!/usr/bin/env python3
"""
ats_fetch.py — shared, pagination-correct fetch layer for every ATS this
project talks to. Used by discover_ats.py (to log true per-company totals
when validating/revalidating an endpoint) and by poll_jobs.py (to actually
retrieve every posting on each run).

WHY THIS EXISTS
---------------
The first pass at discover_ats.py validated an endpoint with a single GET
and trusted whatever count came back. Several ATSes page their results by
default, so that count was frequently just the page size, not the real
total:

  - SmartRecruiters caps at 100 per page (`limit` is silently clamped to
    100 even if you ask for more) and reports the true count in
    `totalFound` — four different companies here all "coincidentally"
    showed exactly 100, which was the tell.
  - Amazon's public search defaults to `result_limit=10`.
  - Workday's CXS API hard-caps `limit` at 20 — anything higher silently
    returns zero results instead of an error, which is its own trap.

Every fetch_* function below returns a FetchResult with the FULL list of
postings (paginating until the server itself says there's no more) plus
enough metadata to sanity-check the result — because pagination has its
own trap: Workday's CXS `total` field is itself capped (confirmed live:
Accenture and NVIDIA both report exactly "total": 2000, and paging past
offset 2000 silently WRAPS AROUND and re-serves the same jobs from
offset 0 instead of erroring). So every paginator also de-duplicates by
each posting's own stable id and stops the moment a page's first item is
one we've already seen, rather than trusting the server's stated total.

Amazon has the mirror-image problem: its global (unfiltered) search caps
`hits` at exactly 10000 (a plain Elasticsearch max_result_window), which
is meaningless as "Amazon's true global job count" and not worth fully
paginating. This tool only cares about Bulgaria, so fetch_amazon_all
filters server-side with the *documented* `country=BGR` param (found by
inspecting amazon.jobs' own search network traffic — an earlier attempt
at `normalized_country_code[]` was the wrong param name and silently
returned zero every time) instead of hauling down the global set to
filter client-side.

Every function is polite: one request in flight at a time, throttled by
PAGE_SLEEP_SECONDS between calls to the same endpoint.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobSearchDiscovery/1.0; "
    "personal job-monitoring tool; contact via LinkedIn)"
}
TIMEOUT = 10

# Sleep between successive requests — both pages of the same paginated
# fetch and, in poll_jobs.py, between distinct companies. poll_jobs.py's
# brief is explicit: 1 second between requests.
PAGE_SLEEP_SECONDS = 1.0

# Hard ceilings so a server misbehaving (e.g. a total that never counts
# down, or wraparound going undetected for some reason) can't spin forever.
MAX_PAGES = 120
MAX_JOBS = 6000

# A wraparound (see _paginate) caught within this many pages is treated as
# unreliable ranking, not a real small total — see the Accenture finding in
# _paginate's wraparound branch.
LOW_CONFIDENCE_PAGE_THRESHOLD = 3

WORKDAY_PAGE_SIZE = 20  # confirmed hard cap: anything higher returns 0 results
SMARTRECRUITERS_PAGE_SIZE = 100  # confirmed hard cap regardless of requested limit
AMAZON_PAGE_SIZE = 100


@dataclass
class FetchResult:
    jobs: list
    reported_total: Optional[int]  # what the API's own metadata field said (may be capped/misleading)
    true_total: int  # len(jobs) after de-duping — what we actually confirmed exists
    pages_fetched: int
    capped: bool = False  # hit MAX_PAGES/MAX_JOBS or detected server-side wraparound
    low_confidence: bool = False  # wraparound hit almost immediately — number is likely an undercount, not a real total
    warnings: list = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.true_total > 0


def _sleep():
    time.sleep(PAGE_SLEEP_SECONDS)


# A large board can take 40-100+ sequential requests to fully paginate; over
# that many round-trips a single transient blip (timeout, connection reset,
# a 502 from a load balancer) is likely, not exceptional. Confirmed live: a
# DXC fetch died mid-pagination on exactly this kind of one-off failure.
# Without a retry, that silently threw away every page already collected.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _with_retries(do_request: Callable[[], object]):
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        result = do_request()
        last = result
        if isinstance(result, requests.RequestException):
            pass  # network-level failure — retry
        elif getattr(result, "status_code", None) not in _RETRYABLE_STATUS:
            return result  # success or a non-retryable error (e.g. 404) — done
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    return last


def _get(url: str, params: dict | None = None):
    def do():
        try:
            return requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            return e
    return _with_retries(do)


def _post(url: str, body: dict):
    def do():
        try:
            return requests.post(url, headers=HEADERS, json=body, timeout=TIMEOUT)
        except requests.RequestException as e:
            return e
    return _with_retries(do)


def _paginate(
    fetch_page: Callable[[int], tuple[list, Optional[int]] | None],
    page_size: int,
    id_key: Callable[[dict], str],
) -> FetchResult:
    """Shared pagination engine.

    fetch_page(offset) -> (items_on_this_page, reported_total_or_None), or
    None on a request error. Stops when a page is empty, when the first
    item on a page has an id we've already collected (wraparound), or when
    a safety ceiling is hit.
    """
    jobs: list = []
    seen_ids: set[str] = set()
    reported_total = None
    pages = 0
    capped = False
    low_confidence = False
    warnings: list[str] = []
    warned_total_disagreement = False
    offset = 0

    while True:
        if pages >= MAX_PAGES or len(jobs) >= MAX_JOBS:
            capped = True
            warnings.append(
                f"Stopped after safety ceiling ({pages} pages / {len(jobs)} jobs) "
                f"— server may have more, or may be wrapping around."
            )
            break

        result = fetch_page(offset)
        if result is None:
            return FetchResult(
                jobs=jobs, reported_total=reported_total, true_total=len(jobs),
                pages_fetched=pages, capped=capped, low_confidence=low_confidence,
                warnings=warnings, error="request failed",
            )
        items, total = result
        pages += 1
        # Only trust the FIRST page's total. Confirmed live on Workday: page 1
        # reports the real (if itself capped) total, but every later page
        # reports total=0 even though items keep coming — overwriting on
        # every page would make that flakiness kill pagination after page 2.
        if reported_total is None and total is not None:
            reported_total = total
        elif (
            total is not None and total != reported_total and pages > 1
            and not warned_total_disagreement
        ):
            warned_total_disagreement = True
            warnings.append(
                f"Page {pages} (offset {offset}) reported total={total}, "
                f"disagreeing with page 1's total={reported_total} — ignoring "
                f"every later value, keeping page 1's (logged once)."
            )

        if not items:
            break

        first_id = id_key(items[0])
        if first_id in seen_ids:
            capped = True
            warnings.append(
                f"Server wrapped around (offset {offset} re-served an already-"
                f"seen posting) after {len(jobs)} unique postings — its "
                f"'total' field ({reported_total}) is a display cap, not the "
                f"real count. Stopping here."
            )
            # Confirmed live on a Workday tenant (Accenture): the offset
            # where this wraparound first appears is NOT stable — it moved
            # from ~500-560 unique postings on one run down to exactly 20
            # (i.e. wraparound on page 2) on another, with nothing about the
            # board actually changing between runs. That's the tenant's
            # default relevance sort re-ranking between requests, not a real
            # total. A wraparound caught this early is a sign the whole
            # number is unreliable, not just capped — flag it as such rather
            # than reporting e.g. "20" as if it were a solid count.
            if pages <= LOW_CONFIDENCE_PAGE_THRESHOLD:
                low_confidence = True
                warnings.append(
                    f"LOW CONFIDENCE: wraparound hit after only {pages} "
                    f"page(s) — this server's result ordering isn't stable "
                    f"across paginated requests (confirmed: the same "
                    f"endpoint has wrapped anywhere from page 2 to page "
                    f"25+ across different runs). Treat {len(jobs)} as a "
                    f"weak floor, not a real total."
                )
            break

        new_count = 0
        for item in items:
            jid = id_key(item)
            if jid not in seen_ids:
                seen_ids.add(jid)
                jobs.append(item)
                new_count += 1

        if len(items) < page_size:
            break

        offset += page_size
        if reported_total is not None and offset >= reported_total:
            break

        _sleep()

    return FetchResult(
        jobs=jobs, reported_total=reported_total, true_total=len(jobs),
        pages_fetched=pages, capped=capped, low_confidence=low_confidence,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Greenhouse — confirmed (live check) to return every job in one response;
# meta.total always equals len(jobs). No pagination needed, but we still
# cross-check the two against each other as a cheap correctness guard.
# ---------------------------------------------------------------------------
def fetch_greenhouse_all(endpoint: str) -> FetchResult:
    r = _get(endpoint)
    if isinstance(r, Exception) or r is None or r.status_code != 200:
        return FetchResult([], None, 0, 1, error=f"HTTP error ({r})")
    try:
        data = r.json()
    except ValueError:
        return FetchResult([], None, 0, 1, error="non-JSON response")
    jobs = data.get("jobs") or []
    meta_total = (data.get("meta") or {}).get("total")
    warnings = []
    if meta_total is not None and meta_total != len(jobs):
        warnings.append(
            f"meta.total ({meta_total}) != jobs returned ({len(jobs)}) — "
            f"Greenhouse may have started paginating this board; investigate."
        )
    return FetchResult(jobs, meta_total, len(jobs), 1, warnings=warnings)


# ---------------------------------------------------------------------------
# Lever — a single unparameterized call has been confirmed to return every
# posting. We still paginate defensively with skip/limit (documented Lever
# params) in case a very large board ever gets capped by default.
# ---------------------------------------------------------------------------
def fetch_lever_all(slug: str) -> FetchResult:
    base = f"https://api.lever.co/v0/postings/{slug}"

    def page(offset: int):
        r = _get(base, params={"mode": "json", "limit": 100, "skip": offset})
        if isinstance(r, Exception) or r is None or r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        if not isinstance(data, list):
            return None
        return data, None  # Lever doesn't expose a total field

    return _paginate(page, page_size=100, id_key=lambda j: j.get("id") or j.get("hostedUrl", ""))


# ---------------------------------------------------------------------------
# Ashby — confirmed (live check) to return every job in one response; no
# documented offset/limit params. Single call.
# ---------------------------------------------------------------------------
def fetch_ashby_all(slug: str) -> FetchResult:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = _get(url)
    if isinstance(r, Exception) or r is None or r.status_code != 200:
        return FetchResult([], None, 0, 1, error=f"HTTP error ({r})")
    try:
        data = r.json()
    except ValueError:
        return FetchResult([], None, 0, 1, error="non-JSON response")
    jobs = data.get("jobs") or []
    return FetchResult(jobs, len(jobs), len(jobs), 1)


# ---------------------------------------------------------------------------
# SmartRecruiters — confirmed: `limit` is silently clamped to 100 no matter
# what you ask for, and `totalFound` is the real count (Experian: 415 total
# vs. 100 returned on a single call). Paginate with offset until we've
# collected totalFound, or a page returns short.
# ---------------------------------------------------------------------------
def fetch_smartrecruiters_all(slug: str) -> FetchResult:
    url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"

    def page(offset: int):
        r = _get(url, params={"offset": offset, "limit": SMARTRECRUITERS_PAGE_SIZE})
        if isinstance(r, Exception) or r is None or r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        return data.get("content") or [], data.get("totalFound")

    return _paginate(page, page_size=SMARTRECRUITERS_PAGE_SIZE, id_key=lambda j: j.get("id", ""))


# ---------------------------------------------------------------------------
# Workday — confirmed: `limit` hard-caps at 20 (21+ silently returns zero
# results, not an error). `total` is ALSO capped by the tenant's search
# backend (Accenture and NVIDIA both report exactly 2000, and offset 2000
# re-serves the exact same postings as offset 0 — a live wraparound, not a
# coincidence). Paginate at 20/page; the shared _paginate() engine's
# wraparound detector is what actually protects this one.
# ---------------------------------------------------------------------------
def fetch_workday_all(endpoint: str) -> FetchResult:
    def page(offset: int):
        body = {"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE, "offset": offset, "searchText": ""}
        r = _post(endpoint, body)
        if isinstance(r, Exception) or r is None or r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        return data.get("jobPostings") or [], data.get("total")

    return _paginate(page, page_size=WORKDAY_PAGE_SIZE, id_key=lambda j: j.get("externalPath", ""))


# ---------------------------------------------------------------------------
# Amazon — confirmed: default result_limit=10 (the "suspiciously round 10"
# in the brief). The *unfiltered* global search also hard-caps hits at
# exactly 10000 (a plain Elasticsearch max_result_window — confirmed by
# probing past offset 9900 until the request itself starts erroring), so
# fully paginating the global set is both wasteful and meaningless as a
# "true total". Since this project only cares about Bulgaria, filter
# server-side with `country=BGR` — the real param name, found by watching
# amazon.jobs' own search network traffic (an earlier guess at
# `normalized_country_code[]` was wrong and silently returned 0 every
# time). That makes `hits` an honest, small, fully-paginable number.
# ---------------------------------------------------------------------------
def fetch_amazon_all(country: str = "BGR") -> FetchResult:
    url = "https://www.amazon.jobs/en/search.json"

    def page(offset: int):
        r = _get(url, params={"result_limit": AMAZON_PAGE_SIZE, "offset": offset, "country": country})
        if isinstance(r, Exception) or r is None or r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        return data.get("jobs") or [], data.get("hits")

    return _paginate(page, page_size=AMAZON_PAGE_SIZE, id_key=lambda j: j.get("id_icims") or j.get("job_path", ""))


# ---------------------------------------------------------------------------
# Recruitee, Breezy HR, Workable — each confirmed (live check) to return
# every posting in a single, unparameterized call. No documented pagination
# params for any of the three; nothing to loop.
# ---------------------------------------------------------------------------
def fetch_recruitee_all(slug: str) -> FetchResult:
    url = f"https://{slug}.recruitee.com/api/offers/"
    r = _get(url)
    if isinstance(r, Exception) or r is None or r.status_code != 200:
        return FetchResult([], None, 0, 1, error=f"HTTP error ({r})")
    try:
        data = r.json()
    except ValueError:
        return FetchResult([], None, 0, 1, error="non-JSON response")
    offers = data.get("offers") or []
    return FetchResult(offers, len(offers), len(offers), 1)


def fetch_breezy_all(slug: str) -> FetchResult:
    url = f"https://{slug}.breezy.hr/json"
    r = _get(url)
    if isinstance(r, Exception) or r is None or r.status_code != 200:
        return FetchResult([], None, 0, 1, error=f"HTTP error ({r})")
    try:
        data = r.json()
    except ValueError:
        return FetchResult([], None, 0, 1, error="non-JSON response")
    if not isinstance(data, list):
        return FetchResult([], None, 0, 1, error="unexpected response shape")
    return FetchResult(data, len(data), len(data), 1)


def fetch_remote_all(endpoint: str) -> FetchResult:
    """Remote.com's public job board. One request returns every open job, no paging."""
    r = _get(endpoint)
    if isinstance(r, Exception) or r is None or r.status_code != 200:
        return FetchResult([], None, 0, 1, error=f"HTTP error ({r})")
    try:
        jobs = r.json().get("jobs") or []
    except ValueError:
        return FetchResult([], None, 0, 1, error="non-JSON response")
    jobs = [j for j in jobs if j.get("status") == "open" and j.get("accepting_applications")]
    return FetchResult(jobs, len(jobs), len(jobs), 1)


def fetch_workable_all(slug: str) -> FetchResult:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    r = _get(url)
    if isinstance(r, Exception) or r is None or r.status_code != 200:
        return FetchResult([], None, 0, 1, error=f"HTTP error ({r})")
    try:
        data = r.json()
    except ValueError:
        return FetchResult([], None, 0, 1, error="non-JSON response")
    jobs = data.get("jobs") or []
    return FetchResult(jobs, len(jobs), len(jobs), 1)


# ---------------------------------------------------------------------------
# Dispatch by ATS label (as stored in companies.json) + endpoint URL.
# Extracts whatever slug/tenant each fetcher needs out of the endpoint
# itself, so callers don't need to know each ATS's URL shape.
# ---------------------------------------------------------------------------
_GREENHOUSE_RE = re.compile(r"boards-api(?:\.eu)?\.greenhouse\.io/v1/boards/([^/]+)/jobs")
_LEVER_RE = re.compile(r"api\.lever\.co/v0/postings/([^/?]+)")
_ASHBY_RE = re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([^/?]+)")
_SMARTRECRUITERS_RE = re.compile(r"api\.smartrecruiters\.com/v1/companies/([^/]+)/postings")
_RECRUITEE_RE = re.compile(r"https://([^.]+)\.recruitee\.com/api/offers/")
_BREEZY_RE = re.compile(r"https://([^.]+)\.breezy\.hr/json")
_WORKABLE_RE = re.compile(r"apply\.workable\.com/api/v1/widget/accounts/([^/?]+)")

# ATS labels this dispatcher/fetch layer knows how to actually pull postings
# for. Anything else (Avature, Phenom People, Oracle HCM, SuccessFactors
# HTML career pages, HiBob SPA, proprietary portals, ...) has no public feed
# and stays MANUAL — there is nothing here to paginate.
FETCHABLE_ATS = {
    "Greenhouse", "Lever", "Ashby", "SmartRecruiters", "Workday",
    "Amazon (proprietary JSON API)", "Recruitee", "Breezy HR", "Workable", "Remote",
}


def fetch_all(ats: str, endpoint: str) -> FetchResult:
    """Route to the right paginated fetcher for a (ats, endpoint) pair."""
    if ats == "Greenhouse":
        return fetch_greenhouse_all(endpoint)
    if ats == "Lever":
        m = _LEVER_RE.search(endpoint)
        return fetch_lever_all(m.group(1)) if m else FetchResult([], None, 0, 0, error="couldn't parse slug")
    if ats == "Ashby":
        m = _ASHBY_RE.search(endpoint)
        return fetch_ashby_all(m.group(1)) if m else FetchResult([], None, 0, 0, error="couldn't parse slug")
    if ats == "SmartRecruiters":
        m = _SMARTRECRUITERS_RE.search(endpoint)
        return fetch_smartrecruiters_all(m.group(1)) if m else FetchResult([], None, 0, 0, error="couldn't parse slug")
    if ats == "Workday":
        return fetch_workday_all(endpoint)
    if ats == "Amazon (proprietary JSON API)":
        return fetch_amazon_all()
    if ats == "Recruitee":
        m = _RECRUITEE_RE.search(endpoint)
        return fetch_recruitee_all(m.group(1)) if m else FetchResult([], None, 0, 0, error="couldn't parse slug")
    if ats == "Breezy HR":
        m = _BREEZY_RE.search(endpoint)
        return fetch_breezy_all(m.group(1)) if m else FetchResult([], None, 0, 0, error="couldn't parse slug")
    if ats == "Workable":
        m = _WORKABLE_RE.search(endpoint)
        return fetch_workable_all(m.group(1)) if m else FetchResult([], None, 0, 0, error="couldn't parse slug")
    if ats == "Remote":
        return fetch_remote_all(endpoint)
    return FetchResult([], None, 0, 0, error=f"no fetcher for ATS {ats!r}")
