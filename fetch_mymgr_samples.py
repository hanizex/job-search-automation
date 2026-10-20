#!/usr/bin/env python3
"""One-off: saves the last My Manager digests (digest@mymgr.app) from Gmail
into samples/mymgr/*.eml so Claude can write the parser offline.
Uses the same Gmail app password as the email digest (.env SMTP_USER/SMTP_PASS).
Read-only: does not change, move or mark any email."""
import email, imaplib, sys
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SENDER = "digest@mymgr.app"
DAYS = 14
KEEP = 5

def load_env(p):
    env = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def main():
    env = load_env(HERE / ".env")
    out = HERE / "samples" / "mymgr"
    out.mkdir(parents=True, exist_ok=True)
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        m.login(env["SMTP_USER"], env["SMTP_PASS"])
    except imaplib.IMAP4.error as e:
        print("LOGIN FAILED:", e)
        sys.exit(1)
    status, _ = m.select('"[Gmail]/All Mail"', readonly=True)
    if status != "OK":
        m.select("INBOX", readonly=True)
    since = (date.today() - timedelta(days=DAYS)).strftime("%d-%b-%Y")
    status, data = m.uid("search", None, "FROM", '"%s"' % SENDER, "SINCE", since)
    uids = data[0].split() if status == "OK" and data and data[0] else []
    print("found %d digests in the last %d days" % (len(uids), DAYS))
    for uid in uids[-KEEP:]:
        status, msgdata = m.uid("fetch", uid, "(BODY.PEEK[])")
        raw = msgdata[0][1]
        msg = email.message_from_bytes(raw)
        try:
            d = parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%d_%H%M")
        except Exception:
            d = "nodate"
        path = out / ("%s_%s.eml" % (d, uid.decode()))
        path.write_bytes(raw)
        print("saved", path.name, "|", msg.get("Subject", "")[:80])
    m.logout()

if __name__ == "__main__":
    main()
