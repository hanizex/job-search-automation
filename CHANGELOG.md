# Changelog

## 0.2.1 - 2026-10-27

### Fixed
- **Workday pagination** (`ats_fetch.py`). A page that repeats the previous one is requested again, up to two times, before the list is treated as wrapped around. A transient glitch on the tenant side no longer cuts a board short or marks it as capped. The page total from the first answer is still the reference.

### Added
- `test_workday_retry.py`: offline tests for the repeat retry, including a Workday fetch with one glitched page.

## 0.2.0 - 2026-10-27

### Added
- **Remote.com source** (`ats_fetch.py`, `"ats": "Remote"`). Reads the public job board API at `apply.remote.com`. One request returns every posting, and only open postings that accept applications are kept. Links point to `https://apply.remote.com/jobs/<id>`.
- **Location priority 1-3** on every kept posting (`priorities.py`, `location_rules.py`).
  - P1: on-site or hybrid in the home city, or fully remote.
  - P2: relocation within Europe, or a country that gives Ukrainians temporary protection (EU, Switzerland, Norway, Iceland, Liechtenstein).
  - P3: needs a work visa (UK, US, Canada, the rest).
  - Dropped: Germany-only and Ukraine-only roles.
- **`SHOW_P3` switch** (`priorities.py`). P3 rows are hidden by default. Set it to `True` to show them at the bottom of the table.
- **Multi-country collapse** (`collapse.py`). One requisition published once per country becomes one row. Title words stay in the collapse key, so different roles never merge.
- **URL facts** (`url_hints.py`). For Workday "N Locations" postings the primary city comes from the posting URL. The requisition id and the title written in the URL go to a new Notes column.
- **Tech-giant board adapters** (`ats.py`): Greenhouse, Ashby, Lever, SmartRecruiters, Recruitee, Workday. They read the `ats` key in `companies.json` and return rows in the shape the poller already consumes.
- **Tests:** `test_priorities.py`, `test_url_hints.py` and `test_patch.py`. All offline, standard library only.

### Changed
- The relocation watch list is retired. Relocation roles are now P2 or P3 rows in the main table.
- The location filter uses the priority scale. Europe-wide and EMEA remote roles pass. US, Canada, LATAM and APAC markers still reject.
- The output table has a Prio column and a Notes column. Rows sort P1, P2, P3, newest first inside each group.
- Titles and locations are HTML-unescaped (Workday sends `&amp;`).
- README and CUSTOMIZE describe the priority scale, the new adapters and the new test files.

### Upgrade notes
- No changes to `.env`.
- Existing `data/companies.json` entries keep working. To add Remote.com, use `"ats": "Remote"` with the endpoint `https://apply.remote.com/api/public/jobs`.
- The home city for priority 1 is set in `location_rules.py` and `priorities.py`. The defaults are Sofia, Bulgaria.

## 0.1.0 - 2026-10-20

- First public version: ATS and job-board polling, title and location filters, ad screening, de-duplication against the tracker, reply classification and funding signals.
