#!/usr/bin/env python3
"""
replies.py - finds employer replies in Gmail for Agent 1 (13.10.2026). No AI.

Reads INBOX over IMAP (same app password as the digest: .env SMTP_USER / SMTP_PASS), read-only:
nothing is moved, deleted or marked as read. Keeps only job-related emails, classifies each:
  rejection | interview | ack (auto "we received your application") | reply (other human reply)
and guesses the company from sender name, sender domain and subject.

Writes data/replies_pool.json (30 days, dedupe by Message-ID) and out/replies_latest.json
(last 7 days, ack excluded). The 08:49 autoimport task matches them to tracker cards.

Standalone check:  python3 replies.py --days 30 --report   (prints a table, writes nothing)
Python 3.9, standard library only.
"""
from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
from datetime import date, datetime, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Callable, List, Optional

ATS_DOMAINS = ("greenhouse.io", "greenhouse-mail.io", "lever.co", "ashbyhq.com", "workable.com",
               "workablemail.com", "smartrecruiters.com", "recruitee.com", "recruitee-mailbox.com", "breezy.hr",
               "breezy-mail.com", "myworkday.com", "workday.com", "teamtailor.com", "teamtailor-mail.com",
               "personio.de", "personio.com", "bamboohr.com", "jobvite.com", "icims.com", "successfactors.com",
               "sapsf.com", "pinpointhq.com", "homerun.co", "comeet.co", "comeet-notifications.com", "jazzhr.com",
               "applytojob.com", "peopleforce.io", "huntflow.io", "cleverstaff.net", "taleo.net", "rippling.com",
               "join.com", "manatal.com", "zohorecruit.com", "dover.com", "jobscore.com", "freshteam.com",
               "hirehive.com", "talentlyft.com", "skillie.ai", "traffit-mail.com", "erecruiter.pl", "jobico.io")
GENERIC_DOMAINS = ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
                   "ukr.net", "abv.bg", "mail.bg", "proton.me", "protonmail.com", "i.ua", "meta.ua")
CC_SLD = ("com.ua", "org.ua", "net.ua", "in.ua", "kiev.ua", "kyiv.ua", "co.uk", "com.pl", "com.cy", "co.il", "com.br")
GENERIC_LOCAL = re.compile(r"^(no-?reply|noreply|donotreply|do-not-reply|notifications?|sender|support|info|hello|hi|"
                           r"careers?|jobs?|hr|recruit\w*|talent|hiring|team|system|mail|email|e\+.*|pfva_.*|\w{10,}\+.*)$", re.I)
SKIP_SENDERS = re.compile(
    r"(mymgr\.app|jobalerts|jobs-noreply@linkedin|jobs-listings@linkedin|linkedin\.com|djinni\.co|dou\.ua|"
    r"dev\.bg|jobs\.bg|justjoin|nofluffjobs|indeed\.|glassdoor|welcometothejungle|wellfound|otta\.com|"
    r"eu-startups|sifted|tech\.eu|crunchbase|substack|medium\.com|google\.com|youtube|calendar-notification|"
    r"anthropic\.com|claude\.ai|github\.com|notion\.so|lovable|sendpulse|facebookmail|work\.ua|robota\.ua|rabota\.ua|"
    r"temuemail|imot\.bg|read\.ai|theresanaiforthat|beehiiv|linear\.app|nic\.ua|pmi\.org|goit\.|apriori\.|"
    r"startup\.lviv|trmnl4|campaign\.|jobsglobal|thesmartjobs|jobs2web|collaborativegain|turing\.com|"
    r"bykovarecruitment)", re.I)
SKIP_SUBJECT = re.compile(
    r"(job alert|jobs? for you|new jobs|jobs? matching|recommended jobs|вакансії для вас|нові вакансії|nuovi lavori|"
    r"newsletter|digest|webinar|unsubscribe|your weekly|top jobs|security alert|verify your|password|пароль|"
    r"log ?in to|login link|aktywuj|zaloguj|complete the application|complete your|gdpr|information request|"
    r"data processing consent|talent pool|for the future|community|explore careers|\[esp\]|request ur\d|"
    r"cannot apply|small talks|changelog|profile is ready|smart tracker|job match)", re.I)
SUBJECT_JOB = re.compile(
    r"(application|applied|applying|candidacy|candidate|position|vacanc|interview|recruit|hiring|\bcv\b|resume|"
    r"manager|owner|delivery|scrum|\brole\b|next step|offer|вакансі|резюме|кандидат|співбесід|відгук|позиці|"
    r"собеседован|отклик|кандидатур|интервю|позиция|kandydat|aplikacj|stanowisk)", re.I)
BODY_JOB = re.compile(r"(application|applied|applying|candidacy|candidate|position|vacanc|interview|recruit|"
                      r"вакансі|резюме|кандидат|співбесід|відгук|собеседован|отклик)", re.I)
REJECTION = re.compile(
    r"(unfortunately|not (?:be )?moving forward|not to move forward|decided to (?:move forward|proceed|continue|go ahead) with other|"
    r"will not be (?:moving|progressing|proceeding)|not (?:be )?progress(?:ing)? your|with other candidates|"
    r"position has been filled|role has been filled|regret to inform|not been selected|were not selected|"
    r"won'?t be moving|no longer considering|closer match|more closely match|not a fit|pursue other|"
    r"application results|результати співбесіди|на жаль|не готові рухатись|інших кандидат|іншого кандидата|"
    r"не можемо запропонувати|к сожалению|других кандидат|за съжаление|други кандидати|niestety)", re.I)
ACK_SUBJECT = re.compile(
    r"(thanks? (?:you )?for applying|received your application|application (?:has been )?(?:received|submitted)|"
    r"has reached|we.ve got it|successfully applied|your application as|job application -|"
    r"отримали твою|отримали ваш|дякуємо за відгук|dziękujemy za aplikację)", re.I)
INTERVIEW_SUBJECT = re.compile(
    r"(interview|next step|invitation|запрошення|співбесід|дзвін|зустріч|тестов|собеседован|интервю|"
    r"assessment|video introduction|test task|call with)", re.I)
INTERVIEW_BODY = re.compile(
    r"(calendly\.com|invite you (?:to|for) (?:an? )?(?:interview|call)|schedule (?:an? )?(?:interview|call)|"
    r"book a (?:call|time|slot)|запрошуємо (?:вас )?на (?:співбесіду|інтерв|дзвінок)|"
    r"would (?:like|love) to (?:invite|schedule|arrange)|test task|тестове завдання)", re.I)
QUOTE_CUT = re.compile(r"(\n>|\nOn .{5,120}wrote:|\nВ .{5,80}пише:|написав\(ла\):|написала:|написав:|"
                       r"-----Original Message|\nFrom: |\nОт: |\nВід: |\n_{8,})", re.I)
ROLE_WORDS = re.compile(r"\b(manager|owner|engineer|lead|director|specialist|coordinator|analyst|master|developer|"
                        r"application|update|vacancy|position|role|candidacy|thank|dziękuj|кандидат|вакансі)\b", re.I)
TRAILING = re.compile(r"\s*(talent( acquisition)?|recruiting|recruitment|careers?|hiring|hr|people( team)?|team|jobs|"
                      r"via (greenhouse|lever|workable|ashby|smartrecruiters|teamtailor|recruitee)|"
                      r"notifications?|no-?reply)\s*$", re.I)


def _hdr(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def _body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if not part:
        return ""
    try:
        text = part.get_content()
    except Exception:
        return ""
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?i)<blockquote.*", " ", text, flags=re.S)  # quoted thread
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
    import html as H
    text = H.unescape(text)
    m = QUOTE_CUT.search(text)
    if m:
        text = text[:m.start()]
    return re.sub(r"\s+", " ", text).strip()


def _domain(addr: str) -> str:
    d = addr.split("@")[-1].lower().strip(">")
    parts = d.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in CC_SLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else d


def _is_ats(addr: str) -> bool:
    d = addr.split("@")[-1].lower()
    return any(d == a or d.endswith("." + a) for a in ATS_DOMAINS)


DOMAIN_ALIAS = {"erg.ink": "Emerise Group"}   # company mail domains whose name differs from the company (add here when you spot one)


def company_hint(name: str, addr: str, subject: str) -> str:
    d, local = _domain(addr), addr.split("@")[0]
    if d in DOMAIN_ALIAS:
        return DOMAIN_ALIAS[d]
    if d and d not in GENERIC_DOMAINS and not _is_ats(addr):
        return d.split(".")[0].capitalize()  # personal or careers mailbox at the company's own domain
    def ok(x):
        x = (x or "").strip(" .-!–")
        return x if x and not ROLE_WORDS.search(x) and x.lower() not in ("re", "fw", "fwd", "aw") else ""
    for pat in (r"(?:application (?:to|for|at|with)|applying (?:to|at)|interest in|position at|role at|"
                r"opportunity at|career at|vacancy at|from|від|в)\s+(?:the\s+)?([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})",
                r"\bat\s+([\w&.\-]+(?:\s+[A-Z][\w&.\-]*){0,2})\s+-",          # "... at intent - ..."
                r"^\s*(?:re:\s*|fwd?:\s*)?([\w][\w&.\- ]{1,40}?)\s+[-–]\s",   # "Craftware - Dziękujemy ..."
                r"\s[-–]\s+([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})\s*$",   # "Role - Trinetix"
                r"^\s*([A-Z][\w&.\- ]{1,40}?)\s*[:|]"):                       # "ICT Strypes: ..." / "Lynksen | ..."
        m = re.search(pat, subject, re.I if pat.startswith(r"^\s*(?:re") else 0)
        if m and ok(m.group(1)):
            return ok(m.group(1))
    at = re.search(r"\bat\s+(.+)$", name or "", re.I)
    if at and ok(at.group(1)):
        return ok(at.group(1))
    sub = addr.split("@")[-1].lower().split(".")
    if len(sub) > 2 and sub[0] not in ("us", "eu", "mail", "email", "m", "e", "app", "jobs", "inbound", "stage", "updates",
                                       "candidates", "reply", "notifications", "konto", "talent"):
        return sub[0].capitalize()  # acme.recruitee.com / softswiss.teamtailor-mail.com
    if _is_ats(addr):
        if local.startswith("job.") or local.startswith("e+"):
            last = re.split(r"[.+]", local)[-1]
            if last.isalpha():
                return last.capitalize()  # job.xxx.addepto@recruitee-mailbox.com
        elif "." not in local and not GENERIC_LOCAL.match(local):
            return re.sub(r"[-_](jobs?|careers?|hr|recruit\w*)$", "", local).capitalize()  # broadcom@myworkday.com
    n = TRAILING.sub("", TRAILING.sub("", re.sub(r"[\"']", "", name or "").strip()))
    if n and not re.search(r"(no-?reply|notification|greenhouse|lever|workable|ashby|recruitee|teamtailor)", n, re.I) \
            and len(n.split()) <= 4:
        return n
    return ""


STRONG_REJ = re.compile(REJECTION.pattern.replace("unfortunately|", "").replace("|на жаль", "")
                        .replace("|к сожалению", "").replace("|niestety", ""), re.I)


def classify(subject: str, body: str) -> str:
    if ACK_SUBJECT.search(subject):  # "Thank you for applying" can still be a rejection - only strong phrases count
        return "rejection" if STRONG_REJ.search(body[:3000]) else "ack"
    if REJECTION.search(subject) or REJECTION.search(body[:3000]):
        return "rejection"
    if INTERVIEW_SUBJECT.search(subject) or INTERVIEW_BODY.search(body[:3000]):
        return "interview"
    return "reply"


def parse_message(raw: bytes) -> Optional[dict]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    name, addr = parseaddr(_hdr(msg.get("From")))
    subject = re.sub(r"\s+", " ", _hdr(msg.get("Subject"))).strip()
    addr = addr.lower()
    if not addr or SKIP_SENDERS.search(addr) or SKIP_SUBJECT.search(subject):
        return None
    body = _body_text(msg)
    ats = _is_ats(addr)
    bulk = bool(msg.get("List-Unsubscribe")) or (msg.get("Precedence", "").lower() in ("bulk", "list"))
    if not ats:
        if bulk and not REJECTION.search(subject + " " + body[:1500]):
            return None  # newsletters and marketing from non-ATS senders
        if not SUBJECT_JOB.search(subject):
            if not (BODY_JOB.search(body[:1500]) and (REJECTION.search(body[:3000]) or INTERVIEW_BODY.search(body[:3000]))):
                return None
        if _domain(addr) in GENERIC_DOMAINS and not re.search(r"(interview|співбесід|вакансі|position|vacanc|offer)", subject, re.I):
            return None  # private gmail etc.: only clear job subjects
    try:
        dt = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)
    return {"msg_id": (msg.get("Message-ID") or "").strip() or f"{addr}|{subject}|{dt.isoformat()}",
            "date": dt.date().isoformat(), "from_name": name.strip(), "from_addr": addr,
            "domain": _domain(addr), "subject": subject[:200], "snippet": body[:300],
            "kind": classify(subject, body), "company_hint": company_hint(name, addr, subject)}


def fetch(env: dict, days: int, log: Callable[[str], None]) -> List[dict]:
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    rows = []
    try:
        m.login(env["SMTP_USER"], env["SMTP_PASS"])
        m.select("INBOX", readonly=True)
        since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = m.uid("search", None, "SINCE", since)
        uids = data[0].split() if status == "OK" and data and data[0] else []
        me = env["SMTP_USER"].lower()
        for uid in uids:
            status, msgdata = m.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK" or not msgdata or not msgdata[0]:
                continue
            r = parse_message(msgdata[0][1])
            if r and r["from_addr"] != me:
                rows.append(r)
        log(f"Replies: scanned {len(uids)} inbox email(s) from {days} day(s), {len(rows)} job-related")
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return rows


def _load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def run(log: Callable[[str], None], data_dir: Path, out_dir: Path, days: int = 4,
        env_path: Path = Path(".env"), latest_days: int = 7) -> int:
    rows = fetch(_load_env(env_path), days, log)
    pool_path = data_dir / "replies_pool.json"
    try:
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        pool = {}
    new = 0
    for r in rows:
        if r["msg_id"] not in pool:
            new += 1
        pool[r["msg_id"]] = r  # re-parsed rows replace old ones (classifier fixes apply to the pool)
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    pool = {k: v for k, v in pool.items() if v["date"] >= cutoff}
    pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    week = (date.today() - timedelta(days=latest_days)).isoformat()
    latest = sorted((v for v in pool.values() if v["date"] >= week and v["kind"] != "ack"),
                    key=lambda v: v["date"], reverse=True)
    (out_dir / "replies_latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {}
    for v in latest:
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    log(f"Replies: {new} new; last 7 days without acks: {len(latest)} " + str(kinds))
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--report", action="store_true", help="print a table only, write nothing")
    ap.add_argument("--latest-days", type=int, default=7, help="one-off backfill: put N days into replies_latest.json")
    a = ap.parse_args()
    if a.report:
        rows = fetch(_load_env(Path(".env")), a.days, print)
        for r in sorted(rows, key=lambda r: r["date"]):
            print(" | ".join([r["date"], r["kind"].ljust(9), (r["company_hint"] or "?")[:25].ljust(25),
                              r["from_addr"][:35].ljust(35), r["subject"][:70]]))
    else:
        run(print, Path("data"), Path("out"), a.days, latest_days=a.latest_days)


if __name__ == "__main__":
    main()
