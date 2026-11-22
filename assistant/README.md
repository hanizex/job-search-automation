# Assistant pack

The engine finds and screens jobs. This pack turns **your own AI chat** (Claude, ChatGPT or Gemini) into the part that knows you: it builds your search profile, your Fact Bank and your Master CV, and then tailors a CV, a cover message and LinkedIn messages for each job you pick.

Nothing here needs code, an API key or a server. You use the chat subscription you already have. **Your data stays with you**: the files below live in your chat project (or a folder, a drive, your own repository). The tracker never needs them.

## Set it up once (about 15 minutes of answering questions)

1. **Create a project in your chat app.** Claude: a Project. ChatGPT: a Project or a custom GPT. Gemini: a Gem.
2. **Paste [`project-instructions.md`](project-instructions.md)** into the project's instructions.
3. **Add the modules** from [`modules/`](modules/) as project files. If your app cannot keep files in a project, paste the module you need at the start of a chat.
4. **Say "Start setup".** The assistant interviews you, one topic at a time, and writes three files for you to save in the project:
   - `profile.json` for the engine, with your match target and notes for the assistant ([`modules/01-profile-interview.md`](modules/01-profile-interview.md))
   - `fact_bank.md`, your facts with evidence ([`modules/02-fact-bank.md`](modules/02-fact-bank.md))
   - `master_cv.md`, your base CV ([`modules/03-master-cv.md`](modules/03-master-cv.md))
5. Put `profile.json` next to the engine (or pass `--profile`). Run the engine, open your tracker, and pick a job.

## Every job

Press **Copy for AI** on a tracker card and paste it into your project chat. The assistant screens the ad for blockers, maps each requirement to your facts, checks the match gate, and, if it passes, gives you the tailored CV, the cover message and the LinkedIn messages ([`modules/04-tailor-to-job.md`](modules/04-tailor-to-job.md)). It ends with a small **card update** block that the tracker's "Apply AI result" button reads, so you do not copy fields by hand.

After an interview, tell the assistant what was asked and how it went ([`modules/05-after-an-interview.md`](modules/05-after-an-interview.md)). New facts go to your Fact Inbox.

## Optional: an online tracker
If you use an online JSE tracker that gives you a personal connector address, add it to your chat app as a custom connector (no sign-in; the address is your key, so keep it private). Then the assistant can read your next job, update the card and keep your search goals current: when you change what jobs you want, it proposes at most 3 search terms, shows the profile, waits for your yes and sends it. The tracker holds jobs and statuses only; your Fact Bank, CV and profile history stay in your project. Without an online tracker everything works as described above.

## What the assistant never does

It never invents a fact, a number or a certificate. It never sends anything, applies for you or contacts anyone. When your facts cannot reach the match target, it stops and names the gaps.

## Keeping your files current

The Fact Bank grows. When something new and true comes up in any chat, the assistant offers to add it to `fact_inbox.md`. How your chat keeps and edits files (project files, an artifact, a drive, your own repository) is up to you and your assistant. Once in a while ask: "Merge my Fact Inbox into the Fact Bank and show me what changed."

## Privacy

Your AI provider sees what you share in your own chat, under your own account. A friendly tip: before you share an interview transcript or a performance review, take out other people's names and anything confidential. The assistant also keeps confidential figures out of the Fact Bank. Your CV, Fact Bank and personal history stay in your own chat; the online tracker never receives them.

## Files

| File | What it is |
|---|---|
| `project-instructions.md` | the instructions to paste into the project |
| `modules/01-profile-interview.md` | interview that writes `profile.json` |
| `modules/02-fact-bank.md` | how facts are collected, checked and kept |
| `modules/03-master-cv.md` | the Master CV structure and rules |
| `modules/04-tailor-to-job.md` | the per-job method, cover and messages, card update |
| `modules/05-after-an-interview.md` | feedback after interviews |
| `templates/` | empty `fact_bank.md`, `fact_inbox.md`, `master_cv.md` |
