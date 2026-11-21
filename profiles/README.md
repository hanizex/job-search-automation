# Search profiles

The engine has no built-in preferences. One JSON file says what a good job means for one person.
**Nobody edits it by hand.** Your AI assistant interviews you and writes it; you only confirm.

Try the engine with an example:

    python3 poll_jobs.py --profile profiles/example_eu_remote_pm.json --dry-run --no-notify

Use your own: save the file as `profile.json` in the project folder (or pass `--profile PATH`, or set `JSE_PROFILE`).
If the file is missing or wrong, the engine says what is missing in plain words.

| Example | Who it is |
|---|---|
| `example_eu_remote_pm.json` | A project manager based in Sofia, open to EU-remote and relocation in Europe (the author's own rules) |
| `example_pl_python_dev.json` | An invented Python developer based in Warsaw |

## What the interview covers (and what each answer controls)

| Topic | Field | Effect |
|---|---|---|
| Roles | `roles.titles` | a posting passes only when its title contains one of these |
| Not wanted | `roles.exclude_title_words` | drops titles with these words (intern, junior, marketing...) |
| Languages | `languages.spoken` | a language you do NOT speak in a title ("German speaking") drops the job |
| Where you live | `location.home_country` | P1: home places, and remote jobs open to your region |
| Where you could move | `location.relocation`, `relocation_secondary` | P2 (groups start with @, for example `@eu`) |
| Never | `location.excluded` | dropped everywhere |
| Visa-only places | derived | P3, hidden unless `show_p3` is true |
| Companies | `companies.exclude` | dropped everywhere |
| What you already have | `background.certificates`, `background.domains`, `background.eu_citizen` | an ad that demands a certificate, an industry or EU citizenship you have is not a blocker; one that demands what you lack is |
| Where to look | `sources.boards`, `sources.dou`, `sources.djinni` | which job boards are read and with which searches. Left empty, the searches are derived from your job titles |

Countries and groups are listed in `geo/places.json`; boards and Djinni keywords in `catalog/sources.json`. The schema is `profiles/profile.schema.json`.

Job ads are read once and judged for the profile (`jd_screen.extract_signals`, then `jd_screen.match`), so one reading can serve many people.

## Prompt for your AI assistant

> Interview me to create my job-search profile for the Job Search Engine. Ask one topic at a time: roles I look for,
> words that make a title not a fit, languages I work in, the country I live in, countries I could move to,
> countries I never want, companies I never want. Use the file `profiles/profile.schema.json` and the country list in
> `geo/places.json`. Also ask what I already have (certificates, industries, EU citizenship), and pick job-board searches from
> `catalog/sources.json` (or leave them out and they are derived from my job titles). When you have no gaps left, show me the result in plain words, then write `profile.json` after I confirm.
