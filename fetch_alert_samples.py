#!/usr/bin/env python3
"""One-off (13.10): counts job-alert emails from LinkedIn, jobs.bg and Welcome to the Jungle
in Gmail (last 30 days) and saves the 3 newest of each into samples/alerts/<source>/*.eml,
so Claude can write parsers. Read-only. Same app password as the digest (.env)."""
import email, imaplib
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from email.header import decode_header, make_header
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = {"linkedin": ["jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com", "jobs-noreply@linkedin.com"],
           "jobsbg": ["jobs.bg"], "wttj": ["welcometothejungle"], "indeed": ["indeed.com"],
           "glassdoor": ["glassdoor"], "wellfound": ["wellfound"]}

def load_env(p):
    env = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
    return env

env = load_env(HERE / ".env")
m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
m.login(env["SMTP_USER"], env["SMTP_PASS"])
if m.select('"[Gmail]/All Mail"', readonly=True)[0] != "OK":
    m.select("INBOX", readonly=True)
since = (date.today() - timedelta(days=30)).strftime("%d-%b-%Y")
for src, senders in SOURCES.items():
    uids = []
    for snd in senders:
        st, data = m.uid("search", None, "FROM", '"%s"' % snd, "SINCE", since)
        if st == "OK" and data and data[0]:
            uids += data[0].split()
    uids = sorted(set(uids), key=int)
    print("%-10s %3d emails in 30 days" % (src, len(uids)))
    out = HERE / "samples" / "alerts" / src
    for uid in uids[-3:]:
        st, md = m.uid("fetch", uid, "(BODY.PEEK[])")
        raw = md[0][1]; msg = email.message_from_bytes(raw)
        try: d = parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%d_%H%M")
        except Exception: d = "nodate"
        out.mkdir(parents=True, exist_ok=True)
        (out / ("%s_%s.eml" % (d, uid.decode()))).write_bytes(raw)
        print("   saved", d, "|", str(make_header(decode_header(msg.get("Subject", ""))))[:70])
m.logout()
