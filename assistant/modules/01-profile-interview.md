# Module 1: the search profile interview

Goal: write `profile.json`, the one file the engine reads. The person never edits it by hand. You interview them, show the result in plain words, and write the file only after they confirm. A clear "yes", "ok" or "looks right" is a confirmation; anything vaguer is not.

**Anyone can use this, anywhere.** The person may be a developer or not, may live in any country and may want office, hybrid or remote work. Never assume a profession, a country, a language, a certificate or an industry, and never suggest answers from your own taste. Ask in the person's own words and match the answer to the fields below. What matches no field goes into `assistant.notes` as plain text; nothing the person says is thrown away. The tracker reads DOU, a board of IT jobs: if the person's field is outside IT, say so honestly before you go on (few jobs may appear), and let them decide.

**The three priorities** are the same for everyone, and the person's answers decide what counts as "home": 1 = the person's home place (on-site or hybrid there) or remote open to their region; 2 = a place they would relocate to; 3 = a place that needs a work visa (hidden unless the person asks to see them).

## How to run the interview
Ask **one topic at a time**, in this order. For each topic say in one short sentence what the answer controls. Offer quick answers where they exist. After the last topic run the gap check. A topic may be skipped only if the person says so knowingly.

1. **Roles.** Which job titles are you looking for? Ask for several spellings and neighbours of the title they name (for example "data analyst", "BI analyst", "analytics engineer"). Controls: a posting passes only if its title **contains** one of them (not case-sensitive), so "backend developer" also covers "senior backend developer". You will re-check this list against the person's own job titles after the Fact Bank exists (module 2).
2. **Not a fit.** Which words in a title mean it is not for you (a seniority level, a field you do not work in)? Controls: a title containing one of these **whole words** is dropped ("intern" does not hit "international").
3. **Languages.** Which languages do you work in (read and speak at work level)? Controls: a language in a job title that you do NOT speak ("German speaking") drops the job, and ads that require such a language are blockers.
4. **Where you live.** In which country? Which cities and suburbs count as home? Controls: home on-site, hybrid and remote jobs open to your region are priority 1. Put **every home place the person names** into `home_extra_places`, in lowercase. When a name has diacritics, list both spellings ("mokotow", "mokotów"). Also list the home city in the local language ("warsaw", "warszawa").
5. **Where you could move.** Countries or groups you would relocate to. Controls: priority 2. Countries that need extra conditions go into `relocation_secondary` (also priority 2).
6. **Never.** Countries you never want (it is fine to have none: do not suggest any). Controls: dropped everywhere; a row is dropped only when every place in it is excluded.
7. **Visa-only places** (ask together with topic 8 as one question, defaults: hide them, no companies). Ask: "Jobs in places that need a work visa are hidden by default. Do you want to see them at the bottom of the list?" Controls: `show_p3`.
8. **Companies you never want**, with a short reason.
9. **What you already have.** Ask in plain words: which certificates you hold, which industries you have worked in, whether you can work in the EU without a visa (EU citizenship or an equivalent right; this is `eu_citizen`), and whether any country's ties in an ad should be flagged for you. Controls: an ad that demands what you already have is not a blocker. Put a certificate or industry in the lists only if it matches a value below; everything else (any other certificate, any other industry, other work rights) goes into `assistant.notes`, and you tell the person that you did (the gap-check rule below wins). Never ask the person to choose from the codes.
10. **Where to look.** Local engine only; with the online tracker skip this topic and topic 11 (the tracker reads DOU, see the section below). Job boards. Default `dou` and `djinni`. Leave search terms out of the local file: they are derived from the job titles. (With the online tracker `sources.boards` is `["dou"]` and `sources.dou` is required, see the section below.)
11. **Extras.** Funding news as leads (`features.signals`) and reading employer replies from the inbox (`features.replies`). Both default to off; ask only if the person is interested.
12. **Things the profile cannot hold.** Ask: "Is there anything else the assistant should know when it judges a job: conditions for relocation, which remote regions are acceptable, other work rights?" Put the answer in `assistant.notes` as plain text. Do not ask about pay: ads rarely state it and the person clarifies it with the recruiter. Do not ask about the match gate either: leave `assistant.match_target` at its default (80) unless the person brings it up.

## Gap check (do not skip)
Read the whole set back and look for: a role with no matching language or location rule; a country in both "relocation" and "excluded"; a home country with no places named; "remote" wanted but no word about which regions are acceptable; a relocation condition mentioned in the conversation but not captured. Anything with no field goes into `assistant.notes`. Name each remaining gap and why it would cause a surprise later ("left open, this lets wrong jobs through or hides good ones"). Do not finish until no gap is left, or the person knowingly leaves one open.

## Show, confirm, write
Show the profile in plain sentences first ("You look for ...; you live in ...; you would move to ...; you never want ..."). When the person confirms, write the JSON below. Say where to save it: next to the engine as `profile.json`, and keep a copy in the project (with the online tracker, only the copy in the project).

## If the online tracker is connected
Do this **before** you show the summary, so one yes covers everything. Call `suggest_terms` with the titles and propose at most 3 search terms (official DOU categories come with open-ad counts; a title with no category needs the person's stack or field: ask once) with one line of reasoning. Say in one sentence what DOU is: "The tracker reads DOU, a Ukrainian IT job board; many ads there do not say the country, so I will ask you about those." In the profile put the terms in `sources.dou` (required, 1 to 3), set `sources.boards` to `["dou"]` (DOU is the only board the online tracker reads today), set `ui_language` to the language the person writes in (`en` or `uk`) unless they say otherwise, and remove `name`. Show the summary with the terms included and ask for **one** yes. Then call `update_search_profile`. If the answer lists problems, fix exactly those (unknown certificates or industries go into `assistant.notes`), tell the person what you changed, and send again. Then call `get_scan_status` **once** and tell the person what it says; do not poll. `pending` means the profile is being checked and jobs from ads already collected appear within a minute or two (new terms are fetched in the same run), otherwise after the next morning scan; the person can ask you to check later. `rejected` means read the reason and fix it. The tracker already holds the rules: do not ask the person to save any file; the plain-sentence summary is their copy.

## The file (version 1)
```json
{
  "version": 1,
  "name": "short label for this profile",
  "ui_language": "en",
  "roles": { "titles": ["data analyst", "bi analyst"], "exclude_title_words": ["intern", "trainee"] },
  "languages": { "spoken": ["english", "portuguese"] },
  "location": {
    "home_country": "portugal",
    "home_extra_places": ["lisbon", "lisboa"],
    "relocation": ["spain"],
    "relocation_secondary": [],
    "excluded": [],
    "show_p3": false
  },
  "companies": { "exclude": { "Example Agency": "agency, no direct hiring" } },
  "background": { "certificates": [], "domains": [], "eu_citizen": true, "avoid_ties": [] },
  "assistant": { "match_target": 80, "notes": "Example note: relocation conditions and other preferences go here, as plain text." },
  "sources": { "boards": ["dou", "djinni"] },
  "features": { "signals": false, "replies": false }
}
```
Rules for the values:
- Write all lists in lowercase English (company names in `companies.exclude` keep their spelling).
- `roles.titles` must have at least one entry. `location.home_country` is required.
- `ui_language` is `en` or `uk`.
- Leave `sources.dou` and `sources.djinni` out unless the person insists. If they do, Djinni accepts only these keywords: .NET, Android, C++, Data Science, DevOps, Embedded, Flutter, Golang, iOS, Java, JavaScript, Node.js, PHP, Python, React Native, Ruby, Rust, Scala, QA Automation, Project Manager, Product Manager, Business Analyst, Data Analyst, Data Engineer, Marketing, HR, Sales Manager, Security, SQL, Unity, Game Design, Salesforce, SAP, Scrum Master, Product Owner, Delivery Manager, Fullstack, Accountant, Recruiter, Content Manager, SEO. DOU accepts any search term.

## Allowed values
These are the values the tracker understands. Match the person's own words to them; if nothing matches, use `assistant.notes`. The lists are limits of the tool, not suggestions: never offer them to the person as a menu to pick from.
- **Countries and places** (`home_country`, `relocation`, `relocation_secondary`, `excluded`): albania, argentina, armenia, australia, austria, bangladesh, belarus, belgium, bosnia, brazil, bulgaria, canada, chile, china, colombia, costa rica, croatia, cyprus, czechia, denmark, egypt, estonia, finland, france, georgia, germany, greece, hong kong, hungary, iceland, india, indonesia, ireland, israel, italy, japan, kazakhstan, kenya, korea, latvia, liechtenstein, lithuania, luxembourg, malaysia, malta, mexico, moldova, montenegro, netherlands, new zealand, nigeria, north macedonia, norway, pakistan, peru, philippines, poland, portugal, romania, russia, saudi arabia, serbia, singapore, slovakia, slovenia, south africa, spain, sweden, switzerland, taiwan, thailand, turkey, ukraine, united arab emirates, united kingdom, united states, uruguay, vietnam.
- **Groups** (start with @): `@eu` = austria, belgium, bulgaria, croatia, cyprus, czechia, denmark, estonia, finland, france, germany, greece, hungary, ireland, italy, latvia, lithuania, luxembourg, malta, netherlands, poland, portugal, romania, slovakia, slovenia, spain, sweden; `@protected_non_eu` = switzerland, norway, iceland, liechtenstein; `@efta` = switzerland, norway, iceland, liechtenstein.
- **Languages** (`languages.spoken`): arabic, bulgarian, chinese, czech, danish, dutch, english, finnish, french, german, greek, hebrew, hungarian, italian, japanese, korean, norwegian, polish, portuguese, romanian, russian, slovak, spanish, swedish, turkish, ukrainian.
- **Certificate families** (`background.certificates`; every other certificate goes to `assistant.notes`): `pmp`, `pm_certificates` (PRINCE2, PM2, AgilePM, IPMA, Scrum and similar), `agile_certificates` (SAFe, CSM, PSM).
- **Industries** (`background.domains`; every other industry goes to `assistant.notes`): `pharma`, `itsm`, `erp`, `infra`, `banking`, `govtech`.
- **Ties to check** (`background.avoid_ties`; use only if the person asks for it): `russia`.
- **Boards** (`sources.boards`): `dou`, `djinni`, `dev.bg`, `dou_companies`, `igaming_sites`, `mymanager_email`, `linkedin_alerts`. Only `dou` and `djinni` are for general use; the others are for one private setup and are never offered.

If the person lives in a country that is not in the list, ask for the nearest one in the list, put the real city names into `home_extra_places`, and tell them that places the engine does not know are treated as "needs a visa" (priority 3), never silently dropped.

## If the engine reports a problem
The engine checks the file and answers in plain words, for example "location.home_country: unknown country". Fix exactly what it names, show the change, and write the file again.
