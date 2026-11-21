# Customize it

Almost everything personal lives in **one file, your search profile** (`profile.json`). You do not edit it by hand: your AI assistant interviews you and writes it. See [profiles/README.md](profiles/README.md) for the fields, the interview prompt and two examples.

This page covers what the profile does *not* decide.

## Which companies to watch

`data/companies.json` is the scan list: the companies whose career system is read directly. An example with 9 companies is included. Build your own with `discover_ats.py`; it reads a numbered company list from `data/07_TIER1_LIST.md` and checks each ATS endpoint. `data/company_rules.json` holds exclusions, aliases and scoring weights for `suggest_companies.py`.

## Which job boards and searches

`sources.boards` in the profile lists the boards (default `dou`, `djinni`). The searches come from your job titles through `catalog/sources.json`, or you set `sources.dou` and `sources.djinni` yourself. To teach the engine a new role, add a rule to `role_map` in `catalog/sources.json`.

## A new kind of blocker in job ads

`jd_rules.py` holds the screening rules. Each rule has an English and a Ukrainian label, a `group`, a `kind` (`always`, `ctx` or `office`), patterns, and a `needs` condition that says when the blocker applies to a person (a residency, a language, a certificate, a domain...). After editing, run `python3 test_jd_screen.py` and `python3 test_screen_profiles.py` and update the expected verdicts to match.

## A country or city the catalogue does not know

`geo/places.json` lists countries with names, main cities and regions. Add your own entry, or put extra names for your home place in `location.home_extra_places` in the profile.

## Output language

`ui_language` in the profile (`en` or `uk`) selects the language of labels and reports. Texts are in `i18n.py` and the rule labels in `jd_rules.py`.

## Email (optional)

Copy `.env.example` to `.env` and fill in a Gmail address and a Google **App Password**, not your normal password. Without `.env`, a normal `poll_jobs.py` run still writes `out/latest.md`, but stops with an error at the email step when there are new postings. The inbox reader (`replies.py`, `features.replies`) also needs it. `--dry-run` works without `.env`.

## Quick check after customizing

```bash
python3 demo_offline.py
python3 poll_jobs.py --dry-run --no-notify
```

`--dry-run` fetches and filters, but writes nothing and sends no email. It is safe to run as often as you like.
