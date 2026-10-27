"""
url_hints.py - facts that a posting's own URL carries, so they can confirm or correct the list data.

A job URL is real data from the employer's system, not a guess. Examples seen on live boards:

  Workday  /job/Warszawa-Poland/Global-Workplace-EMEA-..-Program-Manager_1216360-1
           -> location slug (the list API only says "2 Locations"), the title as it was when the
              ad was created, the requisition id
  Workday  /job/Sofia-Sofia-Bulgaria/HPC-Cluster-Senior-Administrator-in-US-time-zone_1198815-2
           listed as "DevOps Engineer": the slug reveals the original title AND a US-hours requirement
  Recruitee /o/channel-marketing-enablement-manager-mfd-fixed-term-maternity-cover
  Djinni   /jobs/123456-senior-product-manager/      Amazon /en/jobs/10542059/area-manager
  SmartRecruiters /Company/744000149686309-analista-...   (slug present only on links that carry it)

Nothing here is invented: every value is a transformation of text already in the URL, and the callers
label it as coming from the URL. The slug is lossy (punctuation becomes hyphens, case is lost), so a
slug title is shown as a hint next to the real title, never instead of it.

hints(url) -> dict with any of: kind, location, title, req_id   (empty dict when nothing is recognised)
"""
import re
from urllib.parse import urlsplit

_WD = re.compile(r"/job/([^/?#]+)/([^/?#]+)")
_REQ_SUFFIX = re.compile(r"^(?P<title>.*?)_(?P<req>[A-Za-z]{0,4}-?\d{3,}[A-Za-z]?)(?:-\d+)?$")
_RECRUITEE = re.compile(r"/o/([^/?#]+)")
_DJINNI = re.compile(r"/jobs/(\d+)-([^/?#]+)")
_AMAZON = re.compile(r"/jobs/(\d+)/([^/?#]+)")
_SR = re.compile(r"smartrecruiters\.com/[^/]+/(\d+)-([^/?#]+)", re.I)


def _words(slug):
    """'Product-Owner--Community' -> 'Product Owner Community'"""
    out = re.sub(r"[-_]+", " ", slug).strip()
    return re.sub(r"\s+", " ", out)


def _dedupe_runs(text):
    """'Sofia Sofia Bulgaria' -> 'Sofia Bulgaria' (Workday repeats city and region)."""
    words, out = text.split(), []
    for w in words:
        if not out or out[-1].lower() != w.lower():
            out.append(w)
    return " ".join(out)


def _workday(url):
    m = _WD.search(url)
    if not m:
        return {}
    loc_slug, tail = m.group(1), m.group(2)
    # "---" is Workday's " - " (e.g. "Ireland---Dublin"); plain hyphens separate words
    location = _dedupe_runs(_words(loc_slug.replace("---", "-\u00a7-")).replace("\u00a7", "-"))
    t = _REQ_SUFFIX.match(tail)
    title_slug, req = (t.group("title"), t.group("req")) if t else (tail, None)
    out = {"kind": "workday", "location": location, "title": _words(title_slug)}
    if req:
        out["req_id"] = req
    return out


def hints(url):
    if not url or not url.startswith("http"):
        return {}
    host = urlsplit(url).netloc.lower()
    if host.endswith("myworkdayjobs.com"):
        return _workday(url)
    if "recruitee.com" in host or "/o/" in url and "careers." in host:
        m = _RECRUITEE.search(url)
        return {"kind": "recruitee", "title": _words(re.sub(r"-\d+$", "", m.group(1)))} if m else {}
    if host.endswith("djinni.co"):
        m = _DJINNI.search(url)
        return {"kind": "djinni", "req_id": m.group(1), "title": _words(m.group(2))} if m else {}
    if host.endswith("amazon.jobs"):
        m = _AMAZON.search(url)
        return {"kind": "amazon", "req_id": m.group(1), "title": _words(m.group(2))} if m else {}
    if host.endswith("smartrecruiters.com"):
        m = _SR.search(url)
        return {"kind": "smartrecruiters", "title": _words(m.group(2))} if m else {}
    return {}


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "all", "genders"}


def _tokens(text):
    return {w for w in _TOKEN.findall((text or "").lower()) if len(w) >= 3 and w not in _STOP}


def titles_differ(listed, slug_title, threshold=0.5):
    """True when the listed title and the URL's title share less than half their words.
    Non-Latin text in the listed title is ignored (the slug is ASCII), so '... - Стаж' is not a difference."""
    a, b = _tokens(listed), _tokens(slug_title)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) < threshold
