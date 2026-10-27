# Customize it for your own search

The code ships with the rules from my own search: Delivery / Project / Product Manager roles, based in Sofia (Bulgaria), open to EU-remote, no relocation to Germany. Before you run it for yourself, go through the settings below and replace my values with yours. Every setting is a plain Python constant or a JSON file. Nothing is hidden in a database.

## 1. Which roles to look for

**`poll_jobs.py` → `TITLE_KEYWORDS`.** The job titles that pass the first filter. Mine: Delivery / Project / Program / Product Manager, Scrum Master, Product Owner and similar.
Replace them with your own titles, for example `"data engineer"` or `"ux designer"`.

**`job_filters.py` → `JUNIOR_OR_OFFSCOPE`.** Title words that are always dropped (intern, junior, marketing...). Adjust this to your seniority.

## 2. Where you can work

**`poll_jobs.py` → `EU_COUNTRIES`, `ACCEPT_KEYWORDS`, `NON_EU_ONLY_MARKERS`.** These decide which locations are in scope. Mine: Bulgaria / Sofia, the EU, and remote within Europe.

**`job_filters.py` → `HOME`.** Your home city / country. On-site and hybrid roles there are accepted. Mine: `bulgaria|sofia`.

**`job_filters.py` → `COUNTRIES`, `CITY_TO_COUNTRY`, `_hard_excludes()`.** Country rules: which countries go to the relocation watch list and which are dropped. Mine: Germany dropped, Poland- or Ukraine-only remote dropped.

**`job_filters.py` → `LANG_IN_TITLE`.** Roles that require a language in the title ("German speaking") are dropped. Remove the languages you speak.

**`location_rules.py` and `priorities.py`.** The location priority of every kept row. P1 is the home city on-site or hybrid, or fully remote. P2 is relocation within Europe, or a country that gives Ukrainians temporary protection (EU, Switzerland, Norway, Iceland, Liechtenstein). P3 needs a work visa. Germany-only and Ukraine-only are dropped. The home city is set in these two files; the defaults are Sofia, Bulgaria.

**`priorities.py` → `SHOW_P3`.** P3 rows are hidden by default. Set it to `True` to show them at the bottom of the table.

## 3. Hidden blockers inside the ad text

**`jd_rules.py` → `RULES`.** The "wall list" that is checked against the body of each ad. Each rule has a level:
- `wall`: skip automatically
- `ask`: open the ad and check yourself
- `note`: just mention it

Mine cover country residency, on-site outside Sofia, required languages, mandatory certifications (PMP, PRINCE2...), domain gates and Russia ties.

Rule labels are shown in Ukrainian on my tracker cards. Translate the `label` fields if you like.

After editing, run `python3 test_jd_screen.py` and update the expected verdicts in that file to match your rules.

## 4. Where to look

**`data/companies.json`.** The companies whose ATS is polled directly. An example with 9 companies is included. Build your own list with `discover_ats.py` (it reads a numbered company list from `data/07_TIER1_LIST.md` and validates each ATS endpoint).

**`ats.py` → `ADAPTERS`** and **`ats_fetch.py` → `FETCHABLE_ATS`.** The ATS families the poller reads. Remote.com is one of them: `"ats": "Remote"` with the endpoint `https://apply.remote.com/api/public/jobs`.

**`boards.py` → `DEVBG_LISTS`, `DOU_FEEDS`, `DJINNI_LISTS`.** Job-board search pages and feeds. Mine target Bulgarian and Ukrainian PM categories. Replace the URLs with the searches you would open by hand.

**`boards.py` → `TEAMTAILOR_FEEDS`, `SOFTSWISS_URLS`, `DELASPORT_URL`, `EGT_URL`, `UPLATFORM_URL`.** One-off career pages of companies I follow. Remove them or add your own.

**`boards.py` → `MYMGR_SENDER`, `LI_SENDERS`.** Job-alert emails that are read from your inbox (My Manager, LinkedIn alerts). They need `.env`.

## 5. Company list maintenance

**`data/company_rules.json`.**
- `exclude`: companies you never want suggested, each with a reason
- `aliases`: different spellings of one company
- `weights`, `thresholds`: how `suggest_companies.py` scores companies from your tracker

## 6. Funding signals (optional)

**`signals.py` → `FEEDS`, `PRIORITY_SECTORS`, `COUNTRY_HINTS`.** Which startup-news feeds are read, which sectors are flagged as priority, and which regions count. Mine: Europe, CEE and Ukraine; iGaming, FinTech, EdTech, HRTech, E-commerce, AI and others.

## 7. Email (optional)

Copy `.env.example` to `.env` and fill in a Gmail address and a Google **App Password**, not your normal password. Without `.env`, a normal `poll_jobs.py` run still writes `out/latest.md`, but stops with an error at the email step when there are new postings. The inbox readers (`replies.py`, LinkedIn / My Manager alerts) also need it. `--dry-run` works without `.env`.

## Quick check after customizing

```bash
python3 test_jd_screen.py
python3 poll_jobs.py --dry-run --no-notify
```

`--dry-run` fetches and filters, but writes nothing and sends no email. It is safe to run as often as you like.
