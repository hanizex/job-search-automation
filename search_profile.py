"""
search_profile.py - the search profile: everything personal about what a good job means for one person.

The engine has no built-in preferences. It reads one JSON file (profile.json, or the path given with
--profile or the JSE_PROFILE environment variable). The person never edits it by hand: an AI assistant
interviews them and writes it (see profiles/README.md and profiles/profile.schema.json).

Standard library only, Python 3.9 compatible.

    search_profile.use("profiles/example_eu_remote_pm.json")   # or a dict
    cfg = search_profile.compiled()                      # derived sets and regexes, cached
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import geo
import sources as _sources

SCHEMA_VERSION = 1
DEFAULT_PATH = "profile.json"
ENV_VAR = "JSE_PROFILE"

DEFAULTS = {
    "version": SCHEMA_VERSION,
    "name": "",
    "ui_language": "en",
    "roles": {"titles": [], "exclude_title_words": []},
    "languages": {"spoken": ["english"]},
    "location": {
        "home_country": "",
        "home_extra_places": [],
        "relocation": [],
        "relocation_secondary": [],
        "excluded": [],
        "scoped_out": None,        # marker groups; None = derived from the home country's region
        "scoped_out_names": None,
        "show_p3": False,
    },
    "companies": {"exclude": {}},
    "assistant": {
        "match_target": 80,       # percent of the ad's requirements your confirmed facts must cover before a CV is built (the AI assistant uses it, the engine ignores it)
        "notes": "",              # things the profile has no field for: pay floor, relocation conditions, acceptable remote regions
    },
    "features": {
        "signals": False,          # funding / grant news as leads (signals.py), regions and sectors are set in that file
        "replies": False,          # read employer replies from your inbox, read-only (replies.py); needs .env
    },
    "sources": {
        "boards": ["dou", "djinni"],   # which job boards to read (see catalog/sources.json)
        "dou": None,                   # DOU search terms; None = derived from roles.titles
        "djinni": None,                # Djinni keywords (must be known ones); None = derived from roles.titles
    },
    "background": {
        "certificates": [],        # families you hold: pmp, pm_certificates (PRINCE2, PM2, AgilePM...), agile_certificates (SAFe, CSM, PSM...)
        "domains": [],             # industries you have worked in: pharma, itsm, erp, infra, banking, govtech
        "eu_citizen": False,       # citizen of an EU country: "EU citizens only" ads do not block you
        "avoid_ties": [],          # places whose ties in an ad you want to check first: russia
    },
}

CERTIFICATE_FAMILIES = ("pmp", "pm_certificates", "agile_certificates")
DOMAINS = ("pharma", "itsm", "erp", "infra", "banking", "govtech")
AVOID_TIES = ("russia",)


class ProfileError(ValueError):
    """The profile is missing something or names something the engine does not know. The message is plain language."""


_ACTIVE = None   # normalised profile dict
_COMPILED = None


def _merge(base, over):
    out = {}
    for k, v in base.items():
        if isinstance(v, dict):
            out[k] = _merge(v, over.get(k) or {}) if isinstance(over.get(k) or {}, dict) else dict(v)
        else:
            out[k] = over[k] if k in over else v
    for k, v in over.items():     # keep unknown keys (future fields, notes) untouched
        if k not in out:
            out[k] = v
    return out


def _lower_list(x):
    return [str(i).strip().lower() for i in (x or []) if str(i).strip()]


def normalise(raw: dict) -> dict:
    """Merge with defaults, lower-case the lists and check every value. Raises ProfileError listing ALL problems."""
    if not isinstance(raw, dict):
        raise ProfileError("The profile must be a JSON object.")
    p = _merge(DEFAULTS, raw)
    problems = []
    if p.get("version") != SCHEMA_VERSION:
        problems.append(f"Profile version {p.get('version')!r} is not supported (expected {SCHEMA_VERSION}).")

    r = p["roles"]
    r["titles"] = _lower_list(r.get("titles"))
    r["exclude_title_words"] = _lower_list(r.get("exclude_title_words"))
    if not r["titles"]:
        problems.append("roles.titles is empty: list at least one job title you are looking for (for example \"project manager\").")

    p["languages"]["spoken"] = _lower_list(p["languages"].get("spoken"))
    for lang in p["languages"]["spoken"]:
        if lang not in geo.language_keys():
            problems.append(f"languages.spoken: unknown language {lang!r}. Known: {', '.join(sorted(geo.language_keys()))}.")

    loc = p["location"]
    loc["home_country"] = str(loc.get("home_country") or "").strip().lower()
    if not loc["home_country"]:
        problems.append("location.home_country is empty: name the country you live in (for example \"poland\").")
    elif loc["home_country"] not in geo.country_keys():
        problems.append(f"location.home_country: unknown country {loc['home_country']!r}. Use a name from geo/places.json.")
    loc["home_extra_places"] = _lower_list(loc.get("home_extra_places"))
    for key in ("relocation", "relocation_secondary", "excluded"):
        loc[key] = _lower_list(loc.get(key))
        try:
            geo.expand_countries(loc[key])
        except KeyError as e:
            problems.append(f"location.{key}: unknown country or group {e.args[0]!r}. Countries are listed in geo/places.json, groups start with @ (for example @eu).")
    for key, kind in (("scoped_out", "marker_groups"), ("scoped_out_names", "marker_groups")):
        if loc.get(key) is not None:
            loc[key] = _lower_list(loc[key])
            for name in loc[key]:
                if name not in geo.catalogue()[kind]:
                    problems.append(f"location.{key}: unknown marker group {name!r}.")
    if not isinstance(loc.get("show_p3"), bool):
        problems.append("location.show_p3 must be true or false.")

    ex = p["companies"].get("exclude") or {}
    if not isinstance(ex, dict):
        problems.append("companies.exclude must be an object like {\"Company name\": \"reason\"}.")
        ex = {}
    p["companies"]["exclude"] = {str(k).strip().lower(): str(v) for k, v in ex.items()}

    asst = p["assistant"]
    mt = asst.get("match_target")
    if isinstance(mt, bool) or not isinstance(mt, int) or not 50 <= mt <= 100:
        problems.append("assistant.match_target must be a whole number between 50 and 100.")
    if not isinstance(asst.get("notes"), str) or len(asst["notes"]) > 2000:
        problems.append("assistant.notes must be text of at most 2000 characters.")

    ft = p["features"]
    for key in ("signals", "replies"):
        if not isinstance(ft.get(key), bool):
            problems.append(f"features.{key} must be true or false.")

    src = p["sources"]
    boards = [str(b).strip().lower() for b in (src.get("boards") or [])]
    for b in boards:
        if b not in _sources.board_names():
            problems.append(f"sources.boards: unknown board {b!r}. Known: {', '.join(_sources.board_names())}.")
    src["boards"] = boards
    if src.get("dou") is not None:
        src["dou"] = [str(t).strip() for t in src["dou"] if str(t).strip()]
    if src.get("djinni") is not None:
        canon = {k.lower(): k for k in _sources.djinni_keywords()}
        fixed = []
        for k in src["djinni"]:
            if str(k).strip().lower() not in canon:
                problems.append(f"sources.djinni: {k!r} is not a Djinni keyword (an unknown keyword returns unfiltered jobs). Known: {', '.join(_sources.djinni_keywords())}.")
            else:
                fixed.append(canon[str(k).strip().lower()])
        src["djinni"] = fixed

    bg = p["background"]
    for key, allowed in (("certificates", CERTIFICATE_FAMILIES), ("domains", DOMAINS), ("avoid_ties", AVOID_TIES)):
        bg[key] = _lower_list(bg.get(key))
        for item in bg[key]:
            if item not in allowed:
                problems.append(f"background.{key}: unknown value {item!r}. Allowed: {', '.join(allowed)}.")
    if not isinstance(bg.get("eu_citizen"), bool):
        problems.append("background.eu_citizen must be true or false.")

    if problems:
        raise ProfileError("The search profile has problems:\n- " + "\n- ".join(problems))
    return p


def load(path) -> dict:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(f"Profile file not found: {path}")
    except ValueError as e:
        raise ProfileError(f"{path} is not valid JSON: {e}")
    return normalise(raw)


def use(src) -> dict:
    """Make a profile the active one. src: a path or a dict."""
    global _ACTIVE, _COMPILED
    _ACTIVE = normalise(src) if isinstance(src, dict) else load(src)
    _COMPILED = None
    return _ACTIVE


def locate():
    """Path of the profile to use: JSE_PROFILE, else ./profile.json, else None."""
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env)
    if Path(DEFAULT_PATH).exists():
        return Path(DEFAULT_PATH)
    return None


def active() -> dict:
    if _ACTIVE is None:
        path = locate()
        if path is None:
            raise ProfileError(
                "No search profile found. Ask your AI assistant to create profile.json (see profiles/README.md), "
                "or run with --profile profiles/example_eu_remote_pm.json to try the engine.")
        use(path)
    return _ACTIVE


def _word_re(words):
    words = sorted({w for w in words if w}, key=len, reverse=True)
    if not words:
        return None
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


_EU_WIDE_WORDS = {"eu", "eea", "european union"}


def _home_ad_re(home, extras):
    """Does an ad text name the home place? Names and cities need word boundaries; the local-language names
    (for example Cyrillic spellings) are matched as plain substrings."""
    words = sorted(geo.tokens_of(home) | set(extras), key=len, reverse=True)
    parts = [r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])"]
    local = geo.local_names_of(home)
    if local:
        parts.append("|".join(re.escape(w) for w in local))
    return re.compile("|".join(parts), re.I)


def compiled() -> SimpleNamespace:
    """Everything derived from the active profile, computed once."""
    global _COMPILED
    if _COMPILED is not None:
        return _COMPILED
    p = active()
    loc = p["location"]
    home = loc["home_country"]
    home_tokens = geo.tokens_of(home) | set(loc["home_extra_places"])
    home_names = geo.names_of(home) | set(loc["home_extra_places"])
    reloc_keys = geo.expand_countries(loc["relocation"]) - {home}
    second_keys = geo.expand_countries(loc["relocation_secondary"]) - {home} - reloc_keys
    excl_keys = geo.expand_countries(loc["excluded"]) - {home}
    reloc_keys -= excl_keys
    second_keys -= excl_keys
    reloc_tokens = geo.tokens_for(reloc_keys)
    second_tokens = geo.tokens_for(second_keys)
    excl_tokens = geo.tokens_for(excl_keys)
    all_tokens = geo.all_tokens() | set(loc["home_extra_places"])
    visa_tokens = all_tokens - home_tokens - reloc_tokens - second_tokens - excl_tokens

    regions = geo.regions_of(home)
    eu_words = regions & _EU_WIDE_WORDS
    wide_words = (regions - _EU_WIDE_WORDS) | set(geo.world_words())

    default_scoped = ["outside_europe"] if "europe" in regions else []
    default_scoped_names = ["outside_europe_names"] if "europe" in regions else []
    scoped = loc["scoped_out"] if loc["scoped_out"] is not None else default_scoped
    scoped_names = loc["scoped_out_names"] if loc["scoped_out_names"] is not None else default_scoped_names
    marker_tokens = set()
    for name in scoped:
        marker_tokens |= geo.marker_tokens(name)
    # Region words of other parts of the world ("Remote - APAC", "Remote, Europe" for someone living in the US)
    # also scope a remote job away from the home region.
    other_regions = set()
    for key in geo.country_keys():
        other_regions |= geo.regions_of(key)
    marker_tokens |= other_regions - regions - set(geo.world_words())
    marker_names = set()
    for name in scoped_names:
        marker_names |= geo.marker_tokens(name)

    spoken = set(p["languages"]["spoken"])
    blocked_lang_tokens = []
    for key in geo.language_keys():
        if key not in spoken:
            blocked_lang_tokens += geo.language_tokens(key)

    excl_words = p["roles"]["exclude_title_words"]
    # Pre-filter keywords: names of home and relocation countries, home cities, and the home region's words.
    accept = (home_tokens | {t for k in reloc_keys for t in geo.names_of(k)}
              | (regions - _EU_WIDE_WORDS))

    suggested = _sources.suggest(p["roles"]["titles"])
    dou_terms = p["sources"]["dou"] if p["sources"]["dou"] is not None else suggested["dou"]
    djinni_keywords = p["sources"]["djinni"] if p["sources"]["djinni"] is not None else suggested["djinni"]

    _COMPILED = SimpleNamespace(
        profile=p,
        titles=p["roles"]["titles"],
        off_scope_re=_word_re(excl_words),
        lang_re=_word_re(blocked_lang_tokens),
        home=home, home_tokens=home_tokens, home_names=home_names,
        reloc_keys=reloc_keys, reloc_tokens=reloc_tokens,
        second_keys=second_keys, second_tokens=second_tokens,
        excl_keys=excl_keys, excl_tokens=excl_tokens,
        visa_tokens=visa_tokens, all_tokens=all_tokens,
        wide_re=_word_re(wide_words), eu_wide_re=_word_re(eu_words),
        marker_re=_word_re(marker_tokens), marker_names=marker_names,
        accept_words=accept, accept_re=_word_re(accept),
        show_p3=loc["show_p3"],
        spoken=spoken,
        certificates=set(p["background"]["certificates"]), domains=set(p["background"]["domains"]),
        eu_citizen=p["background"]["eu_citizen"], avoid_ties=set(p["background"]["avoid_ties"]),
        home_in_eu=home in geo.expand_countries(["@eu"]),
        ui_language=p["ui_language"],
        features=p["features"], match_target=p["assistant"]["match_target"],
        boards=p["sources"]["boards"], dou_terms=dou_terms, djinni_keywords=djinni_keywords, unmatched_titles=suggested["unmatched"],
        home_ad_re=_home_ad_re(home, loc["home_extra_places"]),
        exclude_companies=p["companies"]["exclude"],
    )
    return _COMPILED
