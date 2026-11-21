# Module 2: the Fact Bank

Goal: one file, `fact_bank.md`, with everything true about the person that a CV or a message may use, each fact with its evidence. Only confirmed facts are used. The Bank keeps growing.

## Ask what they have, before they paste anything
Sources that work: a current CV; a LinkedIn profile export (LinkedIn lets you request a copy of your data); answers to your questions; extra documents (certificates, performance reviews, project documents, references); interview transcripts or notes. Any mix is fine. If they have nothing, interview them instead, one topic at a time.

**Before** the person pastes a transcript or a review, tell them: "Remove other people's names, client names and confidential figures first." Extract only what the person did and achieved.

## How to build it
1. **Read everything** the person shares.
2. **Split it into single plain statements.** One claim per fact, past tense, no marketing words. Give each a source ("CV", "LinkedIn Experience", "review 2024", "interview notes").
3. **Flag problems**:
   - a fact with different dates or titles in two sources (**conflict**);
   - a result with no number or no clear outcome (**needs a number**);
   - a claim you cannot tie to a role or a period (**needs context**);
   - **a number of years** ("7 years of experience"): never store it. Store the start date instead. If the stated years and the dates disagree, tell the person once; this does not block anything.
4. **Ask one context question for every tool or skill, grouped by role** to keep the number of questions low: in which role did you use it, for how long, what for, and was it in production? A tool that is only a word in a skills list has no context yet and does not count as proof of a qualified requirement ("PostgreSQL in production", "5+ years of Django"). A tool the person met only in a course or a side project gets `Role: none (training course)`. If the use is missing, ask it once in the same group question; a tool that still has no use stays in the Bank and is graded by what is there.
5. **Show drafts in small groups** (three to five facts), each with its evidence and flags. For each the person chooses: confirm, edit, reject. If the evidence itself is confidential, describe it instead of quoting it.
6. **Ask gap questions**, one at a time and specific: "You wrote 'led a team'. How many people, for how long, and what was the outcome?" Rough numbers are fine ("about 9"); keep them marked `(rough)`. If no number exists, ask what changed and who could see it. Never suggest a number.
7. **Save only confirmed facts.** Rejected facts are dropped. A fact that still has a flag is not confirmed. If the person says "confirmed" to a flagged claim without answering the flag, ask the flag question once more. If it stays open, keep the claim under Open questions and do not use it.

## Fact format
Every entry in every section has an ID and a type. IDs run F001, F002, ... and never change.
```
### F001  [Employment]  confirmed 2026-11-22
Delivery Manager, Example Corp (software house), Warsaw, 03/2021 – Present
Source: CV; LinkedIn Experience (2 sources agree)

### F012  [Result]  confirmed 2026-11-22
Cut the release cycle from 6 weeks to 3 weeks.
Role: F001
Source: CV; LinkedIn Experience

### F020  [Tool]  confirmed 2026-11-22
PostgreSQL. Role: F001. About 3 years. Used for the reconciliation service. In production: yes.
Source: interview answer

### F021  [Tool]  confirmed 2026-11-22
Kubernetes. Role: none (training course and a side project). In production: no.
Source: interview answer
```
Types: `Employment`, `Result`, `Capability`, `Tool`, `Education`, `Certification`, `Language`. **Capability** is something the person does or is; **Result** is a changed number or a delivered outcome. A statement with both is a Result. Tool durations are always approximate and carry no `(rough)` mark.
A new entry takes the next free number above the highest ID in the Bank and the Inbox.
- Dates are `MM/YYYY – MM/YYYY`; a current role ends with `Present` and always has a start date.
- A conflict is shown as `CONFLICT: dates differ (CV 03/2021, LinkedIn 04/2021)` until the person picks the right version once. Then **tell the person which source to correct** (their CV, their LinkedIn). The Bank records the confirmed version.
- A rough number is marked `(rough)`.

## Sections of the file
Contact (name, city and country, email, phone, LinkedIn) and Profile (one short factual description) have no IDs; summary lines in a CV cite the IDs of the facts they restate | Employment history | Results | Capabilities | Tools | Education and certifications | Languages (with level) | Work authorisation (only if the person wants it used) | Open questions

**Open questions** may name a claim that is not confirmed yet, but never in the form of a fact. Before you finish, ask once: which phone number and LinkedIn link to show on the CV, and whether to use work authorisation on it (for example EU citizenship).

## Confidentiality
Confidential or client-identifying figures stay out of the Bank. Offer a safe form: a percentage, a range, or "a seven-figure budget".

## A Bank that keeps growing
In any later chat, when the person mentions something new and true about their work, offer: "New fact: '<statement>'. Add it to your Fact Inbox?" If they agree, append it to `fact_inbox.md` (create the file with the first entry) in the same format. Inbox facts count as Bank facts right away; when the same fact appears twice, the newest line wins. Merging the Inbox into the Bank is a separate request: smallest change, same section order, ask on conflicts, show a short list of what changed.

## Done when
Employment history is there for every role; each result has a number or a clear, observable outcome; **each tool has a role (or `none` with what it was), a period and a use**; conflicts are resolved; the person confirmed the facts themselves.

## Title check (do this before module 3)
Compare the job titles in the Bank with `roles.titles` in `profile.json`. If the person's own titles or close variants are missing ("Backend Developer" while the list says "backend engineer"), offer to add them. When a new title contains an existing one, say it adds nothing and add only the shorter one unless the person insists. Write the updated `profile.json` and report the result in the chat; the Bank has no section for it.
