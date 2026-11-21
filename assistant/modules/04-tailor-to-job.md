# Module 4: tailor a CV and messages to one job

Input: a pasted job, usually a tracker card (id, company, role, location, link, screening verdict) plus the full job description. If the description is missing, ask the person to open the source and paste the text; never guess requirements from the title. If the card says the status is already `applied`, stop and ask before building anything new.

## Steps
1. **Screen for blockers first**, before building anything. Check against `profile.json` and the Bank:
   - residency or work authorisation (use `background.eu_citizen` from the profile even when the Bank's work-authorisation section is empty), required languages, mandatory certificates, required industries, office or hybrid outside the person's home place, relocation required;
   - the title: does it contain one of `roles.titles`, and none of `exclude_title_words`? If not, note it (the engine would normally have dropped it);
   - `assistant.notes` in the profile: pay floor, contract type, relocation terms. If the ad states pay, contract type or relocation terms that break a note, mark **ask**, or **wall** if the ad states pay below the floor. If the ad is silent on them, say so in one line.
   Show the result as **wall** (a hard requirement the person does not meet), **ask** (unclear, they should check), **ok**. The card's automatic verdict is a hint; your own reading decides. Ask clarifying questions where the ad is unclear, one at a time; accept the answer by text or by voice transcript.
   **On a wall: stop.** Explain it in up to three sentences (a wall is "a hard requirement you do not meet") and end with one question: "Drop (skip) this job, or overrule the wall?" Write no card-update before the answer. If they say drop, send one card-update: `id`, `status: "skip"` and a one-line `note` naming the wall. No `ats`. If they overrule, go on.
2. **Extract requirements** from the ad and sort them: a list called Requirements, Must have, You have, or wording like "required" = **MUST**; Preferred, Plus, Ideally, Would be great = **SHOULD**; Nice to have = ignored. A bullet without a heading and without such words is SHOULD.
3. **Evidence map.** Treat every bullet of the ad as one weighted item (MUST 2, SHOULD 1). If a bullet joins parts with "and" or a comma list, credit each part separately and average them; with "or", the best part counts. For each item find the best confirmed fact in the **Bank or the Inbox** (cite the fact ID) and grade it:
   - **strong** (credit 1): a fact supports the whole requirement, including any qualifier (years, "in production", scale);
   - **partial** (credit 0.5): a fact supports the topic but not the qualifier, or a tool has a role but no period, or it is listed with no context;
   - **none** (credit 0): no confirmed fact. This is a gap, never an invention.
   Grading rules: a tool's period runs from its `Since` date to the end of its role (or to today, which you must know; ask once if you do not). The dates of the role never count as the tool's period. Add the periods of the same tool across roles. "N+ years" is strong when the period is at least N; a fact that says only "about N years" is partial. Language levels: C1, C2 and native count as fluent; B2 is a good working level and counts as partial against "fluent". A fact that says the qualifier is not met (for example "never in production") gives partial for a bare tool requirement and none for a requirement that names the qualifier.
   Show the map as a table: requirement | weight | fact ID | strength | gap. Keep the words plain for the person: show fact IDs in brackets after the sentence, and say once what the card-update block is for.
4. **Match gate.** Score = sum of (weight × credit) divided by the sum of weights, as a whole percent. Show the arithmetic. The target is `assistant.match_target` in `profile.json` (80 if absent). If the score is below the target, **stop**: name the exact gaps and ask one question: "Do you have a true fact the Bank is missing (I will add it to the Inbox and run again), do you want to skip the job, or do you want to apply knowing the gap?" At the stop send one card-update at once: `id`, `ats` (the score), `note` (score and exact gaps), `next` ("Add a fact, skip, or apply knowingly"). No `status`, `cover` or `msg`. When the person answers "skip", send a second card-update: `id`, `status: "skip"`, `next: "Skipped"` and an optional `note`. Never close a gap by adding a keyword with no fact behind it.
5. **Choose** the Master CV (family) and the language of the CV (the language of the ad, unless the person says otherwise).
6. **Build from scratch** from the Bank and the Master CV. Never start from a previous vacancy's CV. Reorder and emphasise real facts; do not add new ones. Same header and formatting rules as module 3. Up to about 900 words.
7. **Audit before you hand it over**: count the ad's keywords that appear in the CV, the words, any filler; confirm every number, title, date and certificate is in the Bank or Inbox; confirm no confidential figure is in the text. **Keywords** are the tools, skills and domain terms named in the Requirements and Preferred lists. Each item inside parentheses counts separately ("AWS (ECS, S3)" is three); an "or" pair counts once; language requirements and soft skills are not keywords; a generic term ("message queues") counts only when the CV uses those words. Report the words and the keyword count in the `note` ("399 words, 12 of 14 keywords"); you cannot measure pages.
8. **Cover message** (the form field), up to 1000 characters, exactly five parts: (a) greeting; (b) why this ad is relevant, in terms of what the ad says the team needs (for example: "Your ad describes growing the reconciliation and settlement services; that is the kind of work I do"). Do not write "excited", "passionate" or any reason the person has not stated; (c) what you bring and the first steps you would take: skills, tools and ways of working from the Bank, intent and not promises, no achievements and no figures; (d) one sentence inviting a conversation; (e) closing and the name. No company name and no role title. Count the characters.
9. **Message to a person inside the company**, 300 to 500 characters, in the language of the ad: the exact job title and company, why interested, what you would improve **only where it follows from the ad's own text and from a Bank fact** (if the ad names no problem, skip the improvement and state the closest Bank fact instead), and the ask: the contact of the recruiter or hiring manager. Phrase a referral request so it never claims a programme exists ("if you have a referral program, I would be grateful for a referral"). Count the characters.
10. **Message to a recruiter**, 300 to 500 characters: ask who runs the search and what the next step is. For roles that may need a local entity or a visa, ask that first. This message stays in the chat; the tracker has one message field, which holds the message from step 9.
11. **Report, then ask for acceptance.** In short form: the clean CV (as text for the person's Word or Docs template), the cover with its character count, the match score and the arithmetic, the number of words, the keyword count, MUST gaps, the priority from the card, what was emphasised or cut, and the recruiter message. Say plainly that **nothing was submitted**. End with one question: "Do you accept this package?" If the person wants changes, make them and ask again.
12. **Card update, after the answer.** Send one JSON block in a fenced block labelled `card-update`. The tracker's "Apply AI result" button reads it. Include only the fields you change; never send an empty string or `null`.
```card-update
{
  "id": "<the id from the pasted card>",
  "status": "ready",
  "ats": 84,
  "cover": "<the cover message, up to 1000 characters>",
  "msg": "<the message from step 9, up to 500 characters>",
  "note": "Match 84%, 2 pages, 7 of 9 keywords. Gaps: <exact gaps>. Risks: <risks>.",
  "next": "Review, apply online, then write to 1-2 people within 3 days."
}
```
   - `ats` is **the gate score** (a whole percent). The keyword count goes only into `note`.
   - `status`: set `ready` only when the person accepted the package; if they did not, omit `status`. Set `skip` only after the person told you to drop the job. Otherwise omit `status`. (The tracker knows more statuses; they are for the person, and for module 5.)
   - Never overwrite the cover of an applied card.
   After the block, say the `next` text in one sentence. A stop ends with its one question instead.

## After they apply
Remind the person of the one step most people skip: within 3 days, write to 1 or 2 people at the company, using the drafted message.
