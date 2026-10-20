# Job Search Automation

A personal job-search pipeline I built to run my own search for Delivery / Project / Product Manager roles in Bulgaria and EU-remote. Every morning it collects new postings from company career systems and job boards, filters out roles that are not a fit, reads the ad text to catch hidden blockers, removes duplicates, and emails me a short digest. It also picks up employer replies from my inbox and tracks startup funding news as a source of leads.

I approached it the way I run delivery: start from the real process, automate the repetitive parts, keep a human in the loop for decisions, and measure whether each source is worth keeping.

## What it does

| Step | Script | What happens |
|---|---|---|
| **1. Discover** | `discover_ats.py`, `discover_careers.py` | Finds which Applicant Tracking System (ATS) each target company uses and validates a working jobs endpoint |
| **2. Collect** | `poll_jobs.py` → `ats_fetch.py`, `boards.py` | Pulls *all* postings from 9 ATS types and 5 job sources (DEV.BG, DOU, Djinni, LinkedIn & My Manager alert emails) |
| **3. Filter** | `job_filters.py` | Keeps PM-shaped titles in Bulgaria / Europe / Remote; routes relocation-only roles to a separate watch list |
| **4. Screen the ad** | `jd_fetch.py`, `jd_screen.py`, `jd_rules.py` | Downloads the ad text and flags blockers (residency, required languages, on-site outside Sofia, mandatory certifications) as **wall / ask / ok** |
| **5. De-duplicate** | `dedupe.py` | Matches by URL, board job id, and company + similar role against the application tracker |
| **6. Report** | `poll_jobs.py` | Writes `out/latest.md` and sends an email digest with only the postings not seen before |
| **7. Replies** | `replies.py` | Reads the inbox (read-only) and classifies employer emails: rejection / interview / acknowledgement / reply |
| **8. Leads** | `signals.py` | Scans European, CEE and Ukrainian startup news for funding rounds and grants in priority sectors |
| **9. Tune the list** | `suggest_companies.py` | Scores companies by real yield and suggests which to add to or drop from the scan list |

## Design decisions

- **APIs first, no scraping where an API exists.** Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Breezy HR, Workday and Amazon expose public job endpoints. Boards are read at a low rate (3 s between requests), the same pages a person sees.
- **Pagination is a trap, so it is handled explicitly.** SmartRecruiters silently caps pages at 100, Workday caps `limit` at 20 and *wraps around* after 2,000 results. `ats_fetch.py` paginates to the real end and de-duplicates by posting id.
- **Rules, not AI, for screening.** Filters and ad screening are plain, explainable regex rules. Every skip carries a reason, so wrong skips are easy to spot and fix.
- **Read-only and safe by default.** Email access never moves, deletes or marks messages. `--dry-run` writes nothing. A failure in one source never stops the daily run.
- **No credentials in code.** Secrets live in `.env`, which is git-ignored.
- **Minimal dependencies.** Python 3.9+, standard library plus `requests`.

## Quick start

```bash
git clone https://github.com/hanizex/job-search-automation.git
cd job-search-automation
pip3 install -r requirements.txt
cp .env.example .env          # only needed for the email digest / inbox features
python3 test_jd_screen.py     # 54 screening tests
python3 poll_jobs.py --dry-run --no-notify
```

Useful flags for `poll_jobs.py`:

```
--dry-run      fetch and filter, but write nothing and send no email
--no-notify    skip the macOS notification
--report-all   write the full current filtered set to out/all_current.md
--test-email   email the current out/latest.md without fetching
```

I run it daily on macOS via `launchd`. Any cron-style scheduler works.

## Configuration

- `data/companies.json`: the scan list (an example with 9 companies across different ATS types is included). Build your own with `discover_ats.py`.
- `data/company_rules.json`: exclusions, aliases and scoring weights for `suggest_companies.py`.
- `jd_rules.py`: the screening rules. Edit them to match your own constraints.
- Title, location and relocation rules live at the top of `poll_jobs.py` and `job_filters.py`.

Personal data (application tracker, results, logs, saved pages) stays in `data/` and `out/` locally and is git-ignored.

## Notes

The filters and rules reflect my own search (Sofia-based, EU-remote, PM/delivery roles), and some labels in the output are in Ukrainian. The structure is generic: swap the rules and the company list, and it works for any role or market.

---

Built by [Mykola Kalakutskyi](https://github.com/hanizex): Senior Delivery Manager. [LinkedIn](https://linkedin.com/in/hanizex)
