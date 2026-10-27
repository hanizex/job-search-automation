#!/usr/bin/env python3
"""
poll_jobs.py — daily job poller.

Loads every company marked status "OK" in data/companies.json, fetches its
full posting list through ats_fetch.py (the pagination-correct fetch layer
built for discover_ats.py — reused here rather than re-implemented, so
Broadcom/VMware's shared Workday endpoint is still fetched exactly once,
and every ATS-specific pagination/wraparound quirk found earlier is
already handled), filters to delivery/PM-shaped titles in Bulgaria/Europe/
Remote, diffs the result against data/seen.json, and writes only the
postings not seen before to out/jobs_{YYYY-MM-DD}.md and out/latest.md.

    python3 poll_jobs.py                  # normal run
    python3 poll_jobs.py --no-notify      # skip the macOS notification (testing)
    python3 poll_jobs.py --dry-run        # do everything except write seen.json/out/, or send email
    python3 poll_jobs.py --test-email     # email whatever's currently in out/latest.md right now,
                                           # ignoring seen.json and skipping the fetch entirely
    python3 poll_jobs.py --report-all     # write the full current filtered set to
                                           # out/all_current.md; ignores and never touches seen.json

WHY NORMALIZATION LIVES HERE, NOT IN ats_fetch.py
--------------------------------------------------
ats_fetch.py's job ends at "here is every real posting object, exactly as
the ATS returned it, fully paginated." Turning each ATS's own schema into
one consistent (title, location, posted date, apply link) shape is a
domain decision about *this* project's report, so it lives in this
script. Every field below was read from a live sample of that ATS before
being written — see NORMALIZE_ATS docstrings for the exact sample. A
missing field is written literally as "UNKNOWN"; nothing here is ever
guessed from a job's *content* (title/location/date). The one exception —
constructing an apply URL for SmartRecruiters and Workday, whose list
endpoints don't include one — builds it from real, already-present fields
(company id + posting id; tenant host + site + externalPath) using a
pattern confirmed live with a plain GET, not a fabricated link.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
import re
import smtplib
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import ats as ats_adapters  # not `ats`: main() uses `ats` as a loop variable for the ATS label
import ats_fetch
import collapse
import job_filters
import jd_fetch
import priorities
from priorities import NON_EU_MEMBERS_RE as _NON_EU_MEMBERS_RE
import url_hints
import boards
import signals
import replies

RATE_LIMIT_SECONDS = 1.0  # between distinct company/endpoint fetches, per the brief
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
TITLE_KEYWORDS = [
    "delivery manager", "project manager", "program manager",
    "technical program manager", "product manager", "engagement manager",
    "delivery lead", "head of delivery", "portfolio manager",
    # added 11.10 for the job boards (DEV.BG / DOU / Djinni)
    "product owner", "product lead", "head of product", "product director", "director product",
    "director of product", "scrum master", "release manager", "programme manager",
    "проєктн", "проектн", "менеджер проє", "менеджер прое", "продакт",
    "delivery director", "integration manager", "керівник проє", "керівник прое",
]

EU_COUNTRIES = {
    "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic",
    "czechia", "denmark", "estonia", "finland", "france", "germany",
    "greece", "hungary", "ireland", "italy", "latvia", "lithuania",
    "luxembourg", "malta", "netherlands", "poland", "portugal", "romania",
    "slovakia", "slovenia", "spain", "sweden",
}
# Any of these on their own is enough to accept a posting, "Remote" included
# — "Remote" here means unscoped (no non-EU region attached; see below).
ACCEPT_KEYWORDS = {"bulgaria", "sofia", "europe", "emea"} | EU_COUNTRIES

# A posting whose location contains one of these, and NONE of the accept
# keywords above, is scoped to a region we don't want — even if the word
# "Remote" also appears (that was the bug: "United States (Remote)" is a
# US-only remote role, not a Bulgaria/EU-eligible one). Named explicitly in
# the brief: United States, Canada, AMER, LATAM, Australia, APAC.
NON_EU_ONLY_MARKERS = {
    "united states", "usa", "u.s.", "canada", "amer", "latam", "australia", "apac",
}

# 25.10: the markers above only catch the spelled-out names. US-based boards (Stripe, ServiceNow,
# OpenAI, Databricks) write "US-Remote", "us; Remote", "Remote - California", "Remote, Costa Rica", so
# priorities.NON_EU_MEMBERS_RE (US states and cities, Canadian provinces, LATAM and APAC countries,
# whole words only) is consulted too. Same rule as the markers: only when no accept keyword is present.


def title_matches(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in TITLE_KEYWORDS)


_EU_WORD_RE = re.compile(r"\b(eu|eea|european union)\b", re.I)  # "Remote (EU or US)" must not be lost to the US marker


def location_matches(location: str) -> bool:
    loc = (location or "").lower()
    if any(k in loc for k in ACCEPT_KEYWORDS) or _EU_WORD_RE.search(loc):
        return True  # an explicit EU/EEA country, Bulgaria, Europe, or EMEA — always in, remote or not
    if "remote" in loc:
        # "Remote" with no EU/Bulgaria/Europe/EMEA signal — only accept if
        # it isn't scoped to a specifically excluded non-EU region.
        return (not any(m in loc for m in NON_EU_ONLY_MARKERS)
                and not _NON_EU_MEMBERS_RE.search(loc))
    # 26.10: a European city named without its country ("Amsterdam", "Paris", "Dublin") or a
    # region-wide remote without the word "remote" ("Worldwide", "Anywhere") has no accept keyword,
    # so it used to be lost here: 9 Adyen/Checkout.com/ServiceNow roles in the first audit. Let
    # priorities.py decide: P1/P2 pass (still never with a US/Canada/LATAM/APAC marker); P3 does not.
    return (priorities.priority3(location) in (1, 2)
            and not any(m in loc for m in NON_EU_ONLY_MARKERS)
            and not _NON_EU_MEMBERS_RE.search(loc))


# ---------------------------------------------------------------------------
# Posted-date parsing. Displayed date is whatever we can honestly derive
# from the ATS's own field; sort_key is a datetime used only for ordering
# (None sorts as "unknown / oldest"). Never invents a specific day where
# the source only gives a fuzzy range (see _parse_workday_posted).
# ---------------------------------------------------------------------------
def _iso_or_none(raw: Optional[str]) -> Optional[datetime]:
    """Parses an ISO8601 timestamp and returns a naive UTC datetime — sort
    keys are kept naive throughout this module so they can all be compared
    against each other regardless of which ATS they came from."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _date_display_and_sort(dt: Optional[datetime]) -> tuple[str, Optional[datetime]]:
    if dt is None:
        return "UNKNOWN", None
    return dt.date().isoformat(), dt


def _parse_workday_posted(raw: Optional[str]) -> tuple[str, Optional[datetime]]:
    """Workday's postedOn is a fuzzy relative string, not a date. "Posted
    Today"/"Posted Yesterday"/"Posted N Days Ago" translate to an exact,
    real calendar date (today minus N — not a guess, arithmetic on a fact
    the API itself stated). "Posted 30+ Days Ago" only gives a lower bound
    — displaying an exact date for that would be inventing precision the
    source doesn't have, so it's shown as-is and sorts as unknown/oldest."""
    raw = (raw or "").strip()
    today = date.today()
    if raw.lower() == "posted today":
        d = today
    elif raw.lower() == "posted yesterday":
        d = today - timedelta(days=1)
    else:
        m = re.match(r"posted (\d+)(\+?) days? ago", raw, re.IGNORECASE)
        if m and not m.group(2):
            d = today - timedelta(days=int(m.group(1)))
        else:
            return (raw or "UNKNOWN"), None
    return d.isoformat(), datetime(d.year, d.month, d.day)


def _parse_amazon_posted(raw: Optional[str]) -> tuple[str, Optional[datetime]]:
    if not raw:
        return "UNKNOWN", None
    try:
        dt = datetime.strptime(raw, "%B %d, %Y")
    except ValueError:
        return raw, None
    return dt.date().isoformat(), dt


def _parse_sql_style_posted(raw: Optional[str]) -> tuple[str, Optional[datetime]]:
    # Recruitee: "2026-09-15 15:59:04 UTC"
    if not raw:
        return "UNKNOWN", None
    try:
        dt = datetime.strptime(raw.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw, None
    return dt.date().isoformat(), dt


def _parse_plain_date(raw: Optional[str]) -> tuple[str, Optional[datetime]]:
    # Workable: "2026-08-11"
    if not raw:
        return "UNKNOWN", None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return raw, None
    return raw, dt


# ---------------------------------------------------------------------------
# Max-age filter. "posted_sort" is a concrete datetime when we could parse
# an exact day — age is computed from that, no invention involved. The one
# fuzzy case worth naming: Workday's "Posted 30+ Days Ago" has no
# posted_sort (see _parse_workday_posted) because we refuse to invent an
# exact day for it — but the string itself already states a >=30-day floor,
# which is real information, so it's always flagged POSSIBLY STALE rather
# than silently passed through as if its age were unknown. It's never
# dropped outright: we don't know its upper bound, and guessing "definitely
# over 60" would be exactly the kind of invention this project avoids.
STALE_MIN_DAYS = 30
DROP_MAX_DAYS = 60
_FUZZY_STALE_RE = re.compile(r"\b30\+\s*days?\s*ago\b", re.IGNORECASE)


def classify_age(posted_sort: Optional[datetime], posted_display: str, today: date) -> str:
    """Returns 'drop', 'stale', 'fresh', or 'unknown' (no usable date info
    at all — neither filtered nor flagged)."""
    if posted_sort is not None:
        age_days = (today - posted_sort.date()).days
        if age_days > DROP_MAX_DAYS:
            return "drop"
        if age_days >= STALE_MIN_DAYS:
            return "stale"
        return "fresh"
    if _FUZZY_STALE_RE.search(posted_display or ""):
        return "stale"
    return "unknown"


# ---------------------------------------------------------------------------
# Per-ATS normalizers. Each returns a dict with title/location/posted_display/
# posted_sort/apply/hiring_entity — "UNKNOWN" for anything the source didn't
# give us. Field names below were read from one live sample per ATS (see the
# fetch script's development notes); nothing is guessed.
#
# hiring_entity is the posting's OWN company/entity field, when the ATS
# actually exposes one on the posting object itself (Greenhouse's
# company_name, SmartRecruiters' and Breezy's company.name, Amazon's
# company_name) — distinct from the seed list's "source board" name, which
# is just which feed we polled and can cover several legal entities (Bosch
# Group's SmartRecruiters board, Broadcom/VMware's shared Workday board).
# For single-tenant ATSes with no such field on the posting (Lever, Ashby,
# Recruitee, Workable) and for Workday (no per-posting field at all, and
# the one board we know is genuinely multi-entity), it's "UNKNOWN" rather
# than assumed equal to the source board — that assumption is exactly what
# would misattribute a VMware posting to Broadcom.
# ---------------------------------------------------------------------------
def _maybe_tag_remote(location: str, is_remote) -> str:
    if is_remote and "remote" not in (location or "").lower():
        return f"{location} (Remote)" if location and location != "UNKNOWN" else "Remote"
    return location


def normalize_greenhouse(job: dict, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    location = (job.get("location") or {}).get("name") or "UNKNOWN"
    dt = _iso_or_none(job.get("first_published") or job.get("updated_at"))
    posted, sort_key = _date_display_and_sort(dt)
    apply = job.get("absolute_url") or "UNKNOWN"
    hiring_entity = job.get("company_name") or "UNKNOWN"
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity=hiring_entity)


def normalize_lever(job: dict, **_) -> dict:
    title = job.get("text") or "UNKNOWN"
    cats = job.get("categories") or {}
    location = cats.get("location") or ", ".join(cats.get("allLocations") or []) or "UNKNOWN"
    location = _maybe_tag_remote(location, (job.get("workplaceType") or "").lower() == "remote")
    created_ms = job.get("createdAt")
    dt = (
        datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        if isinstance(created_ms, (int, float)) else None
    )
    posted, sort_key = _date_display_and_sort(dt)
    apply = job.get("hostedUrl") or job.get("applyUrl") or "UNKNOWN"
    # Lever boards are single-tenant (one account = one company) and the
    # posting object itself carries no separate company/entity field, so
    # there's nothing "the ATS provides" to extract here.
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity="UNKNOWN")


def normalize_ashby(job: dict, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    location = job.get("location") or "UNKNOWN"
    try:
        secondary = [s["location"] for s in (job.get("secondaryLocations") or []) if s.get("location")]
    except (TypeError, KeyError):
        secondary = []
    if secondary:
        location = ", ".join([location] + secondary) if location != "UNKNOWN" else ", ".join(secondary)
    location = _maybe_tag_remote(location, (job.get("workplaceType") or "").lower() == "remote" or job.get("isRemote"))
    dt = _iso_or_none(job.get("publishedAt"))
    posted, sort_key = _date_display_and_sort(dt)
    apply = job.get("jobUrl") or job.get("applyUrl") or "UNKNOWN"
    # Same as Lever: Ashby boards are single-tenant, no per-posting entity field.
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity="UNKNOWN")


def normalize_smartrecruiters(job: dict, **_) -> dict:
    title = job.get("name") or "UNKNOWN"
    loc = job.get("location") or {}
    location = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("country")) if p
    ) or "UNKNOWN"
    location = _maybe_tag_remote(location, loc.get("remote"))
    dt = _iso_or_none(job.get("releasedDate"))
    posted, sort_key = _date_display_and_sort(dt)
    # The postings *list* endpoint doesn't include a human apply URL (only
    # `ref`, the raw API link). The per-posting detail endpoint does
    # (postingUrl/applyUrl), but fetching that separately for every single
    # posting just to get a link isn't worth it — confirmed live that
    # SmartRecruiters' public board accepts this bare, slug-less URL built
    # from fields we already have (company identifier + posting id) and
    # resolves it directly (HTTP 200, no redirect needed).
    company_id = (job.get("company") or {}).get("identifier")
    job_id = job.get("id")
    apply = f"https://jobs.smartrecruiters.com/{company_id}/{job_id}" if company_id and job_id else "UNKNOWN"
    # SmartRecruiters carries the actual hiring entity per posting — this
    # matters a lot for a company-group board like Bosch's ("BoschGroup"),
    # where individual postings can be a specific Bosch subsidiary rather
    # than "Bosch" itself.
    hiring_entity = (job.get("company") or {}).get("name") or "UNKNOWN"
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity=hiring_entity)


_WORKDAY_URL_RE = re.compile(r"https://([^/]+)/wday/cxs/[^/]+/([^/]+)/jobs")


def normalize_workday(job: dict, *, endpoint: str, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    location = job.get("locationsText") or "UNKNOWN"
    posted, sort_key = _parse_workday_posted(job.get("postedOn"))
    external = job.get("externalPath")
    m = _WORKDAY_URL_RE.search(endpoint)
    if m and external:
        host, site = m.groups()
        apply = f"https://{host}/{site}{external}"
    else:
        apply = "UNKNOWN"
    # Workday job postings carry no per-posting company/entity field at
    # all — the "company" is implicit in which tenant's board you queried,
    # not in the posting object. That's exactly the ambiguity behind
    # Broadcom/VMware sharing one board (see KNOWN_RESULTS in
    # discover_ats.py: "filter results for VMware team names" was a
    # manual heuristic, not a data field) — nothing here to extract.
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity="UNKNOWN")


ISO3_TO_NAME = {
    "BGR": "Bulgaria", "AUT": "Austria", "BEL": "Belgium", "HRV": "Croatia",
    "CYP": "Cyprus", "CZE": "Czechia", "DNK": "Denmark", "EST": "Estonia",
    "FIN": "Finland", "FRA": "France", "DEU": "Germany", "GRC": "Greece",
    "HUN": "Hungary", "IRL": "Ireland", "ITA": "Italy", "LVA": "Latvia",
    "LTU": "Lithuania", "LUX": "Luxembourg", "MLT": "Malta", "NLD": "Netherlands",
    "POL": "Poland", "PRT": "Portugal", "ROU": "Romania", "SVK": "Slovakia",
    "SVN": "Slovenia", "ESP": "Spain", "SWE": "Sweden",
}


def normalize_amazon(job: dict, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    # normalized_location uses raw ISO3 codes (e.g. "Munich, Bavaria, DEU"),
    # which won't match our location filter's country NAMES. Decode the
    # job's own country_code field — this reads real data, it does not
    # assume every result is Bulgaria (fetch_amazon_all's default country
    # filter is just that: a default, not a guarantee about what's in the
    # object actually being normalized here).
    location = job.get("normalized_location") or job.get("city") or "UNKNOWN"
    code = job.get("country_code")
    name = ISO3_TO_NAME.get(code) if code else None
    if name and location != "UNKNOWN" and name.lower() not in location.lower():
        location = f"{location} ({name})"
    posted, sort_key = _parse_amazon_posted(job.get("posted_date"))
    path = job.get("job_path")
    apply = f"https://www.amazon.jobs{path}" if path else "UNKNOWN"
    # Amazon postings name the actual hiring legal entity per posting (e.g.
    # "Amazon Deutschland Services GmbH"), distinct from the generic
    # "Amazon / AWS Bulgaria" seed-list label.
    hiring_entity = job.get("company_name") or "UNKNOWN"
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity=hiring_entity)


def normalize_recruitee(job: dict, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    if job.get("remote"):
        location = "Remote"
        city, country = job.get("city"), job.get("country")
        if city or country:
            location += f" ({', '.join(p for p in (city, country) if p)})"
    else:
        location = ", ".join(p for p in (job.get("city"), job.get("country")) if p) or "UNKNOWN"
    posted, sort_key = _parse_sql_style_posted(job.get("published_at") or job.get("created_at"))
    apply = job.get("careers_url") or "UNKNOWN"
    # Recruitee boards are single-tenant; no separate per-posting entity field.
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity="UNKNOWN")


def normalize_breezy(job: dict, **_) -> dict:
    title = job.get("name") or "UNKNOWN"
    loc = job.get("location") or {}
    location = loc.get("name") or "UNKNOWN"
    location = _maybe_tag_remote(location, loc.get("is_remote"))
    dt = _iso_or_none(job.get("published_date"))
    posted, sort_key = _date_display_and_sort(dt)
    apply = job.get("url") or "UNKNOWN"
    # Breezy does carry a company sub-object per posting.
    hiring_entity = (job.get("company") or {}).get("name") or "UNKNOWN"
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity=hiring_entity)


def normalize_workable(job: dict, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    location = ", ".join(p for p in (job.get("city"), job.get("country")) if p) or "UNKNOWN"
    location = _maybe_tag_remote(location, job.get("telecommuting"))
    posted, sort_key = _parse_plain_date(job.get("published_on") or job.get("created_at"))
    apply = job.get("url") or job.get("application_url") or "UNKNOWN"
    # Workable's account-widget API is single-tenant; no separate entity field.
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity="UNKNOWN")


def normalize_remote(job: dict, **_) -> dict:
    title = job.get("title") or "UNKNOWN"
    location = _maybe_tag_remote(job.get("location") or "UNKNOWN", job.get("workplace") == "remote")
    posted, sort_key = _date_display_and_sort(_iso_or_none(job.get("opened_at")))
    public_id = job.get("public_id")
    apply = f"https://apply.remote.com/jobs/{public_id}" if public_id else "UNKNOWN"
    # Remote's public board is single-tenant (one employer), so no per-posting entity field.
    return dict(title=title, location=location, posted_display=posted, posted_sort=sort_key,
                apply=apply, hiring_entity="UNKNOWN")


NORMALIZERS = {
    "Greenhouse": normalize_greenhouse,
    "Lever": normalize_lever,
    "Ashby": normalize_ashby,
    "SmartRecruiters": normalize_smartrecruiters,
    "Workday": normalize_workday,
    "Amazon (proprietary JSON API)": normalize_amazon,
    "Recruitee": normalize_recruitee,
    "Breezy HR": normalize_breezy,
    "Workable": normalize_workable,
    "Remote": normalize_remote,
}


def normalize_job(ats: str, job: dict, endpoint: str) -> dict:
    fn = NORMALIZERS.get(ats)
    if fn is None:
        raise ValueError(f"no normalizer for ATS {ats!r}")
    norm = fn(job, endpoint=endpoint)
    for k in ("title", "location"):   # Workday sends "Customer Experience &amp; Business Process ..."
        norm[k] = html.unescape(norm[k])
    try:  # Stage A (13.10): remember where the ad text can be read; no network here
        jd_fetch.attach_sources(norm, ats, job, endpoint)
    except Exception:
        pass
    return norm


# ---------------------------------------------------------------------------
# Logging — every run, appended, never overwritten.
# ---------------------------------------------------------------------------
def log(msg: str, log_path: Path) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}"
    print(line)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Email delivery.
# ---------------------------------------------------------------------------
REQUIRED_ENV_KEYS = ("SMTP_USER", "SMTP_PASS", "MAIL_TO")


def load_dotenv(path: Path) -> dict:
    """Minimal .env parser (KEY=VALUE per line, '#' comments, optional
    quotes) — no external dependency, per the project's stdlib-plus-
    requests-only constraint. Returns {} if the file doesn't exist; missing
    keys are the caller's problem to raise on, not this function's."""
    env: dict = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key] = value
    return env


class EmailConfigError(RuntimeError):
    pass


def get_smtp_config(env_path: Path) -> dict:
    """Loads SMTP_USER/SMTP_PASS/MAIL_TO from .env. Raises EmailConfigError
    (never returns a partial/best-effort config) if any is missing or
    empty — the brief is explicit: never skip the send silently."""
    env = load_dotenv(env_path)
    missing = [k for k in REQUIRED_ENV_KEYS if not env.get(k)]
    if missing:
        raise EmailConfigError(
            f"Missing or empty required value(s) in {env_path}: {', '.join(missing)}. "
            f"Email delivery needs all of {', '.join(REQUIRED_ENV_KEYS)} — refusing to "
            f"silently skip the send. Fix {env_path} and re-run."
        )
    return {k: env[k] for k in REQUIRED_ENV_KEYS}


_MD_LINK_RE = re.compile(r"^\[(.*)\]\((.*)\)$")


def _split_md_row(line: str) -> list[str]:
    # Cells are pipe-separated; a cell's own literal "|" was escaped as
    # "\|" when the table was built (see main()), so split only on
    # unescaped pipes and then undo that escaping per-cell.
    parts = [p.strip() for p in re.split(r"(?<!\\)\|", line.strip())]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _md_cell_to_html(cell: str) -> str:
    unescaped = cell.replace("\\|", "|")
    m = _MD_LINK_RE.match(unescaped)
    if m:
        text, url = m.group(1), m.group(2)
        return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'
    return html.escape(unescaped)


def count_markdown_table_rows(md_text: str) -> int:
    """Number of data rows in a '| ... |' GitHub-style table (excludes the
    header and separator lines). Used for --test-email, which has no
    freshly-computed new_postings list to count from."""
    lines = [l for l in md_text.splitlines() if l.strip().startswith("|")]
    return max(0, len(lines) - 2)


def markdown_table_to_html(md_text: str) -> str:
    """Converts the exact markdown table already written to out/*.md into
    an HTML table with clickable apply links — so the emailed content is
    provably the same data as the file, not a second, divergent rendering."""
    lines = [l for l in md_text.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return "<p>(no postings)</p>"
    header_cells = _split_md_row(lines[0])
    data_lines = lines[2:]
    th_cells = "".join(
        f'<th style="border:1px solid #ccc;padding:6px 10px;text-align:left;'
        f'background:#f0f0f0;">{html.escape(c)}</th>'
        for c in header_cells
    )
    row_html = []
    for line in data_lines:
        cells = _split_md_row(line)
        td_cells = "".join(
            f'<td style="border:1px solid #ccc;padding:6px 10px;">{_md_cell_to_html(c)}</td>'
            for c in cells
        )
        row_html.append(f"<tr>{td_cells}</tr>")
    return (
        '<table style="border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;'
        'font-size:13px;">'
        f"<thead><tr>{th_cells}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"
    )


_N_LOCATIONS = re.compile(r"\s*(\d+)\s+locations?\s*$", re.I)


def enrich_from_url(p: dict) -> None:
    """26.10: add what the posting's own URL says (url_hints.py). Workday lists a several-city job as
    "2 Locations"; the URL names the primary city, which is enough for the location filter, and the text says
    where the city came from. Also fills p["notes"], a list shown in the Notes column: the requisition id, and the
    title written in the URL when it differs from the listed title (HPE lists "DevOps Engineer" for a URL that
    says "HPC Cluster Senior Administrator in US time zone")."""
    h = url_hints.hints(p.get("apply"))
    if not h:
        return
    notes = p.setdefault("notes", [])
    m = _N_LOCATIONS.match(p.get("location") or "")
    if m and h.get("location"):
        p["location"] = f'{h["location"]} (primary, from URL, {m.group(0).strip()})'
    if h.get("kind") == "workday" and h.get("req_id"):
        notes.append(f"req {h['req_id']}")
    if h.get("title") and url_hints.titles_differ(p.get("title"), h["title"]):
        notes.append(f'URL title: "{h["title"]}"')


def sort_postings(rows: list) -> list:
    """26.10: priority 1 first, then 2, then 3; inside each priority, newest first. Two stable passes."""
    rows.sort(key=lambda p: p["posted_sort"] or datetime.min, reverse=True)
    rows.sort(key=lambda p: p.get("priority") or 9)
    return rows


def build_postings_table(postings: list[dict]) -> str:
    """Renders a list of normalized posting dicts (already sorted by the
    caller) as the project's standard markdown table. Shared by the normal
    new-postings output and --report-all, so both stay byte-for-byte the
    same format."""
    lines = [
        "| Prio | Source Board | Hiring Entity | Title | Location | Posted | Notes | Apply |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in postings:
        entity_cell = p["hiring_entity"].replace("|", "\\|")
        title_cell = p["title"].replace("|", "\\|")
        loc_cell = p["location"].replace("|", "\\|")
        notes_cell = "; ".join(p.get("notes") or []).replace("|", "\\|")
        apply_cell = f"[Apply]({p['apply']})" if p["apply"] != "UNKNOWN" else "UNKNOWN"
        lines.append(f"| {priorities.label(p.get('priority'))} | {p['source_board']} | {entity_cell} | {title_cell} | {loc_cell} | "
                      f"{p['posted_display']} | {notes_cell} | {apply_cell} |")
    return "\n".join(lines) + "\n"


def build_email_html(md_table: str, count: int, when: date) -> str:
    table_html = markdown_table_to_html(md_table)
    return (
        '<html><body style="font-family:Arial,Helvetica,sans-serif;">'
        f"<h2>{count} new job posting{'s' if count != 1 else ''} — {when.isoformat()}</h2>"
        f"{table_html}"
        "</body></html>"
    )


def send_email(subject: str, html_body: str, config: dict, log_path: Path) -> None:
    """Sends over Gmail SMTP/SSL (port 465). Logs the SMTP exchange's
    outcome — success or failure — on every attempt; re-raises on failure
    so a broken send is never silently swallowed."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["SMTP_USER"]
    msg["To"] = config["MAIL_TO"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    server = None
    try:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        ehlo_code, ehlo_resp = server.ehlo()
        log(f"SMTP EHLO -> {ehlo_code} {ehlo_resp!r}", log_path)
        login_code, login_resp = server.login(config["SMTP_USER"], config["SMTP_PASS"])
        log(f"SMTP LOGIN -> {login_code} {login_resp!r}", log_path)
        refused = server.sendmail(config["SMTP_USER"], [config["MAIL_TO"]], msg.as_string())
        if refused:
            log(f"SMTP SENDMAIL -> completed with refused recipient(s): {refused}", log_path)
        else:
            log(f"SMTP SENDMAIL -> accepted for delivery, no recipients refused "
                f"(from={config['SMTP_USER']!r} to={config['MAIL_TO']!r} subject={subject!r})",
                log_path)
    except smtplib.SMTPResponseException as e:
        log(f"SMTP send FAILED -> code={e.smtp_code} error={e.smtp_error!r}", log_path)
        raise
    except Exception as e:
        log(f"SMTP send FAILED -> {e!r}", log_path)
        raise
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# --test-email: an independent action, not a variant of the normal poll run.
# Sends whatever is currently sitting in out/latest.md right now, ignoring
# seen.json entirely (per the brief) — so it never touches the fetch layer.
# ---------------------------------------------------------------------------
def run_test_email(latest_path: Path, env_path: Path, log_path: Path) -> None:
    log("=== --test-email run started ===", log_path)

    if not latest_path.exists():
        log(f"FATAL: {latest_path} does not exist — nothing to email. "
            f"Run poll_jobs.py normally at least once first.", log_path)
        print(f"FATAL: {latest_path} does not exist.", file=sys.stderr)
        sys.exit(1)

    content = latest_path.read_text(encoding="utf-8")
    count = count_markdown_table_rows(content)
    if count == 0:
        log(f"WARNING: {latest_path} contains no table rows — sending an empty table anyway "
            f"(--test-email sends whatever is there, unconditionally).", log_path)

    today = date.today()
    subject = f"Jobs — {today.isoformat()} — {count} new"
    body = build_email_html(content, count, today)

    try:
        config = get_smtp_config(env_path)
    except EmailConfigError as e:
        log(f"FATAL: {e}", log_path)
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)

    log(f"Sending test email: subject={subject!r} to={config['MAIL_TO']!r} "
        f"({count} row(s) from {latest_path})", log_path)
    try:
        send_email(subject, body, config, log_path)
    except Exception as e:
        log(f"FATAL: test email send failed: {e!r}", log_path)
        print(f"FATAL: test email send failed: {e!r}", file=sys.stderr)
        sys.exit(1)

    log("=== --test-email run finished: sent OK ===", log_path)
    print(f"Test email sent to {config['MAIL_TO']} — subject: {subject!r} ({count} row(s)).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
IMPORT_KEEP_DAYS = 14
BOARD_NAMES = {"DEV.BG", "DOU", "Djinni"}


def write_import_file(new_postings: list, pool_path: Path, out_path: Path) -> None:
    """Keep the last 14 days of new postings in one JSON file for the tracker's Import button.
    Re-importing is safe: the tracker skips cards it already has."""
    try:
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        pool = {}
    today_s = date.today().isoformat()
    for p in new_postings:
        url = p["apply"] if p["apply"] != "UNKNOWN" else ""
        key = url or f"{p['source_board']}|{p['title']}"
        if key in pool:
            continue
        loc, pay = p["location"], ""
        m = re.search(r"\s·\s(\$+|[\$€₴]?\s?\d[\d\s,.–-]*)\s*$", loc)
        if m:
            pay, loc = m.group(1).strip(), loc[:m.start()].strip()
        company = p["hiring_entity"] if p["hiring_entity"] != "UNKNOWN" else p["source_board"]
        board = p["source_board"] if p["source_board"] in BOARD_NAMES else f"сайт компанії ({p['source_board']})"
        row = {"company": company, "role": p["title"], "url": url, "location": loc, "pay": pay,
               "board": board, "posted": p["posted_display"].replace(" (POSSIBLY STALE)", ""),
               "found": today_s}
        for k in ("jd", "jd_verdict", "jd_why", "jd_src"):   # Stage A (13.10)
            if p.get(k):
                row[k] = p[k]
        pool[key] = row
    cutoff = (date.today() - timedelta(days=IMPORT_KEEP_DAYS)).isoformat()
    pool = {k: v for k, v in pool.items() if v["found"] >= cutoff}
    pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    items = sorted(pool.values(), key=lambda v: v["found"], reverse=True)
    out_path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def ats_rows_to_postings(rows: list) -> list:
    """25.10: rows from ats.fetch_all use the patch's shape (company, role, url, location,
    posted, ...). Every other source in this script uses title/apply/hiring_entity/source_board/
    posted_display/posted_sort, so convert once here. hiring_entity stays UNKNOWN: ats.py gets the
    company name from companies.json, not from the posting, and this project never presents a
    guessed value as the posting's own field (see the normalizer notes above)."""
    out = []
    for r in rows:
        posted = (r.get("posted") or "").strip()
        try:
            dt = datetime.strptime(posted, "%Y-%m-%d") if posted else None
        except ValueError:
            dt = None
        out.append(dict(
            title=html.unescape(r.get("role") or "UNKNOWN"),
            location=html.unescape(r.get("location") or "UNKNOWN"),
            posted_display=posted if dt else "UNKNOWN",
            posted_sort=dt,
            apply=r.get("url") or "UNKNOWN",
            hiring_entity="UNKNOWN",
            source_board=r.get("company") or "UNKNOWN",
        ))
    return out


def collapse_postings(rows: list) -> tuple:
    """25.10: one requisition published once per country becomes one card (collapse.py).
    collapse.py reads company/role/url/location, so it works on a thin view of each posting and the
    survivor is mapped back to the real posting dict. Returns (rows, run.log line)."""
    views = []
    for p in rows:
        company = p["hiring_entity"] if p.get("hiring_entity") not in (None, "", "UNKNOWN") else p["source_board"]
        views.append({"company": company, "role": p["title"],
                      "url": p["apply"] if p["apply"] != "UNKNOWN" else "",
                      "location": p["location"], "_row": p})
    merged = collapse.collapse(views, priority_of=priorities.priority3)
    out = []
    for v in merged:
        row = v["_row"]
        if v.get("variants", 1) > 1:
            row = dict(row)
            row["location"] = v["location"]
            row["variants"] = v["variants"]
        row["priority"] = v.get("priority")
        out.append(row)
    return out, collapse.report(views, merged)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--companies", default=Path("data/companies.json"), type=Path)
    ap.add_argument("--seen", default=Path("data/seen.json"), type=Path)
    ap.add_argument("--out-dir", default=Path("out"), type=Path)
    ap.add_argument("--log", default=Path("data/run.log"), type=Path)
    ap.add_argument("--no-notify", action="store_true",
                     help="Skip the macOS notification even if new postings are found.")
    ap.add_argument("--dry-run", action="store_true",
                     help="Do everything but don't write seen.json, out/ files, or send email.")
    ap.add_argument("--env-file", default=Path(".env"), type=Path,
                     help="Path to the .env file holding SMTP_USER/SMTP_PASS/MAIL_TO.")
    ap.add_argument("--test-email", action="store_true",
                     help="Email whatever is currently in out/latest.md immediately, "
                          "ignoring seen.json and skipping the fetch entirely.")
    ap.add_argument("--report-all", action="store_true",
                     help="Write the full current filtered set (title+location+age "
                          "filters applied, seen.json ignored) to out/all_current.md. "
                          "Does not read new_postings against, or write to, seen.json, "
                          "and does not send email or fire the macOS notification.")
    args = ap.parse_args()

    if args.test_email:
        run_test_email(args.out_dir / "latest.md", args.env_file, args.log)
        return

    log("=== Run started ===", args.log)

    if not args.companies.exists():
        log(f"FATAL: {args.companies} not found — run discover_ats.py first.", args.log)
        sys.exit(1)
    companies = json.loads(args.companies.read_text(encoding="utf-8"))
    ok_companies = [c for c in companies if c.get("status") == "OK"]
    log(f"Loaded {len(companies)} companies ({len(ok_companies)} status=OK) from {args.companies}", args.log)

    seen: dict = {}
    if args.seen.exists():
        seen = json.loads(args.seen.read_text(encoding="utf-8"))
    log(f"Loaded {len(seen)} previously-seen posting(s) from {args.seen}", args.log)

    # Dedupe by endpoint (Broadcom/VMware share one Workday board) so it's
    # only fetched once; attribute its postings to the joined company
    # names rather than duplicating every posting under each one, since we
    # have no way to split a shared board's postings back out by company.
    groups: dict[tuple[str, str], list[str]] = {}
    for c in ok_companies:
        groups.setdefault((c["ats"], c["endpoint"]), []).append(c["name"])
    dupe_count = sum(len(v) for v in groups.values()) - len(groups)
    if dupe_count:
        log(f"Deduping: {len(groups)} unique endpoint(s) cover {dupe_count + len(groups)} "
            f"companies ({dupe_count} shared).", args.log)

    all_postings: list[dict] = []
    failed_endpoints: list[str] = []

    for i, ((ats, endpoint), names) in enumerate(groups.items()):
        label = " / ".join(names)
        try:
            fr = ats_fetch.fetch_all(ats, endpoint)
        except Exception as e:  # a company's endpoint misbehaving must never kill the run
            log(f"FAILED [{label}] ({ats}) {endpoint}: unexpected exception {e!r}", args.log)
            failed_endpoints.append(label)
            time.sleep(RATE_LIMIT_SECONDS)
            continue

        if fr.error:
            log(f"FAILED [{label}] ({ats}) {endpoint}: {fr.error}"
                + (f" ({fr.true_total} posting(s) collected before failing, discarded — re-run)" if fr.true_total else ""),
                args.log)
            failed_endpoints.append(label)
        else:
            note = ""
            if fr.low_confidence:
                note = " [LOW CONFIDENCE — unstable pagination, see ats_fetch]"
            elif fr.capped:
                note = " [capped]"
            log(f"OK [{label}] ({ats}): {fr.true_total} posting(s) fetched{note}", args.log)
            for job in fr.jobs:
                try:
                    norm = normalize_job(ats, job, endpoint)
                except Exception as e:
                    log(f"WARN [{label}] ({ats}): failed to normalize one posting, skipping: {e!r}", args.log)
                    continue
                norm["source_board"] = label
                all_postings.append(norm)

        if i < len(groups) - 1:
            time.sleep(RATE_LIMIT_SECONDS)

    # Job boards (11.10): DEV.BG, DOU, Djinni - see boards.py.
    try:
        all_postings.extend(boards.fetch_all(lambda m: log(m, args.log)))
        if not args.dry_run:
            boards.update_market_watch(lambda m: log(m, args.log), Path("data"), args.out_dir)
    except Exception as e:
        log(f"FAILED job boards block: {e!r}", args.log)

    # Tech-giant boards (25.10): Greenhouse / Ashby / Lever / SmartRecruiters via ats.py.
    # Only rows written in the patch's own format are passed in (lowercase "ats", e.g. "greenhouse").
    # Older rows ("Greenhouse", status "OK") are read by the ats_fetch loop above, and ats.fetch_all
    # lower-cases "ats" and "status", so without this filter it would also pick those up and fail on
    # them (they carry "endpoint", not token/slug) or fetch them twice. Workday giants are stored in
    # the older endpoint format on purpose (ats.py's Workday adapter returns no posting dates).
    try:
        ats_rows, ats_errors = ats_adapters.fetch_all(
            [c for c in companies if c.get("ats") in ats_adapters.ADAPTERS], log=lambda m: log(m, args.log))
        all_postings.extend(ats_rows_to_postings(ats_rows))
        for name, msg in ats_errors:
            log(f"FAIL [{name}]: {msg}", args.log)
    except Exception as e:
        log(f"FAILED ats.py block: {e!r}", args.log)

    # Funding / grant signals (12.10): independent of job results, never blocks the run.
    if not args.dry_run:
        try:
            signals.run(lambda m: log(m, args.log), Path("data"), args.out_dir)
        except Exception as e:
            log(f"FAILED signals block: {e!r}", args.log)
        # Employer replies in Gmail (13.10): rejection / interview / reply -> out/replies_latest.json.
        try:
            replies.run(lambda m: log(m, args.log), Path("data"), args.out_dir)
        except Exception as e:
            log(f"FAILED replies block: {e!r}", args.log)

    log(f"Fetched {len(all_postings)} raw posting(s) across {len(groups)} unique endpoint(s) "
        f"({len(failed_endpoints)} failed: {', '.join(failed_endpoints) if failed_endpoints else 'none'})",
        args.log)

    for p in all_postings:
        enrich_from_url(p)

    title_filtered = [p for p in all_postings if p.get("trusted_title") or title_matches(p["title"])]  # trusted: his own LinkedIn alerts (14.10)
    log(f"{len(title_filtered)}/{len(all_postings)} posting(s) matched a target title", args.log)

    matched = [p for p in title_filtered if location_matches(p["location"])]
    log(f"{len(matched)}/{len(title_filtered)} posting(s) also matched the location filter", args.log)

    today = date.today()
    age_filtered = []
    dropped_stale_count = 0
    flagged_stale_count = 0
    unknown_age_count = 0
    for p in matched:
        verdict = classify_age(p["posted_sort"], p["posted_display"], today)
        if verdict == "drop":
            dropped_stale_count += 1
            continue
        if verdict == "stale":
            flagged_stale_count += 1
            p["posted_display"] = f"{p['posted_display']} (POSSIBLY STALE)"
        elif verdict == "unknown":
            unknown_age_count += 1
        age_filtered.append(p)
    log(f"{len(age_filtered)}/{len(matched)} posting(s) survived the age filter "
        f"({dropped_stale_count} dropped as >{DROP_MAX_DAYS}d old, "
        f"{flagged_stale_count} flagged POSSIBLY STALE at {STALE_MIN_DAYS}-{DROP_MAX_DAYS}d, "
        f"{unknown_age_count} with no usable posted date)", args.log)
    matched = age_filtered

    # Second pass (11.10; relocation list retired 25.10): language gates, Ukraine-only, tracker
    # duplicates, and a location priority 1-3 on every kept row. See job_filters.py / priorities.py.
    tracker_idx = job_filters.load_tracker_index(Path("data/tracker_export.json"))
    main_rows, drop_reasons = [], {}
    for p in matched:
        verdict, reason = job_filters.classify(p, tracker_idx)
        if verdict == "main":
            main_rows.append(p)
        else:
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
    by_priority = Counter(p.get("priority") for p in main_rows)
    log(f"{len(main_rows)}/{len(matched)} posting(s) kept (by priority: "
        + ", ".join(f"p{k} {by_priority[k]}" for k in sorted(by_priority, key=lambda x: (x is None, x)))
        + "); dropped: "
        + (", ".join(f"{k} {v}" for k, v in drop_reasons.items()) or "none"), args.log)
    # 25.10: after the drops, before the cross-source dedupe: one requisition published per country -> one card.
    # (The tracker comparison already ran inside classify above, so every country variant of a job in the
    # tracker was dropped there; what is left here is only jobs that are new to the tracker.)
    main_rows, collapse_line = collapse_postings(main_rows)
    log(collapse_line, args.log)
    # Same job from two sources (e.g. DEV.BG and the company's own ATS): keep the first.
    deduped, seen_jobs = [], set()
    for p in main_rows:
        company = p["hiring_entity"] if p["hiring_entity"] != "UNKNOWN" else p["source_board"]
        k = (re.sub(r"\W+", " ", company.lower()).strip(), re.sub(r"\W+", " ", p["title"].lower()).strip())
        if k in seen_jobs:
            continue
        seen_jobs.add(k)
        deduped.append(p)
    if len(deduped) != len(main_rows):
        log(f"Cross-source duplicates removed: {len(main_rows) - len(deduped)}", args.log)
    matched = deduped

    if args.report_all:
        report_path = args.out_dir / "all_current.md"
        ordered = sort_postings(list(matched))
        content = build_postings_table(ordered)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(content, encoding="utf-8")
        log(f"--report-all: wrote {len(ordered)} posting(s) (current filtered set, seen.json "
            f"ignored and NOT modified) to {report_path}", args.log)
        print(f"{len(ordered)} posting(s) written to {report_path}")
        log("=== Run finished (--report-all) ===", args.log)
        return

    for p in matched:
        p["_key"] = p["apply"] if p["apply"] != "UNKNOWN" else (
            f"{p['source_board']}|{p['title']}|{p['location']}|{p['posted_display']}"
        )

    new_postings = [p for p in matched if p["_key"] not in seen]
    log(f"{len(new_postings)} posting(s) not previously in {args.seen} "
        f"({len(matched) - len(new_postings)} already seen)", args.log)

    if not args.dry_run:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for p in matched:
            if p["_key"] not in seen:
                seen[p["_key"]] = {"first_seen": now_iso, "source_board": p["source_board"], "title": p["title"]}
        args.seen.parent.mkdir(parents=True, exist_ok=True)
        args.seen.write_text(json.dumps(seen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"Updated {args.seen} ({len(seen)} total entries)", args.log)
    else:
        log("--dry-run: not writing seen.json", args.log)

    if not new_postings:
        log("No new postings this run — writing no output file.", args.log)
        print("No new postings.")
        return

    # All posted_sort values are naive datetimes (see _iso_or_none) or None
    # (unknown/imprecise — sorts as oldest), so this comparison is safe.
    sort_postings(new_postings)

    # Stage A (13.10): read the body of every new ad and look for walls (jd_rules.py). Never blocks the run.
    try:
        jd_fetch.enrich_and_screen(new_postings, lambda m: log(m, args.log),
                                   None if args.dry_run else args.out_dir)
    except Exception as e:
        log(f"JD screen block failed (non-fatal): {e!r}", args.log)

    content = build_postings_table(new_postings)

    if args.dry_run:
        log(f"--dry-run: would have written {len(new_postings)} new posting(s); not writing out/ files.", args.log)
        print(content)
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        write_import_file(new_postings, Path("data/import_pool.json"), args.out_dir / "import_latest.json")
    except Exception as e:  # the import file is a convenience; never block the email
        log(f"Import file not written: {e!r}", args.log)
    dated_path = args.out_dir / f"jobs_{date.today().isoformat()}.md"
    latest_path = args.out_dir / "latest.md"
    dated_path.write_text(content, encoding="utf-8")
    latest_path.write_text(content, encoding="utf-8")
    log(f"Wrote {len(new_postings)} new posting(s) to {dated_path} and {latest_path}", args.log)

    if not args.no_notify:
        message = f"{len(new_postings)} new jobs"
        try:
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "Job Agent"'],
                check=False, capture_output=True, timeout=10,
            )
        except Exception as e:
            log(f"Notification failed (non-fatal): {e!r}", args.log)

    # Email is sent only when there's at least one new posting — we only
    # reach this point at all when new_postings is non-empty (the earlier
    # "if not new_postings: return" above already handles "send nothing on
    # zero new"). Missing/empty credentials here are a hard failure, not a
    # silent skip: we found something worth reporting and can't report it.
    today = date.today()
    subject = f"Jobs — {today.isoformat()} — {len(new_postings)} new"
    body = build_email_html(content, len(new_postings), today)
    try:
        config = get_smtp_config(args.env_file)
    except EmailConfigError as e:
        log(f"FATAL: {e}", args.log)
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
    log(f"Sending email: subject={subject!r} to={config['MAIL_TO']!r} ({len(new_postings)} posting(s))",
        args.log)
    try:
        send_email(subject, body, config, args.log)
    except Exception as e:
        log(f"FATAL: email send failed: {e!r}", args.log)
        print(f"FATAL: email send failed: {e!r}", file=sys.stderr)
        sys.exit(1)

    print(f"{len(new_postings)} new posting(s) written to {latest_path} and emailed to {config['MAIL_TO']}")
    log("=== Run finished ===", args.log)


if __name__ == "__main__":
    main()
