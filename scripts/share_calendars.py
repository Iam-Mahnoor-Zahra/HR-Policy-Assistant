"""Share both calendars (read only) with every employee email in the Supabase employees table.

Run from the project root:
    python -m scripts.share_calendars --dry-run     (only shows who would get access)
    python -m scripts.share_calendars               (does it, no emails are sent)
    python -m scripts.share_calendars --invite      (does it, and Google emails each NEWLY added person)

Safe to run again: emails that already have access are skipped (and get no new invitation).
The subscribe link printed for each calendar adds it to a person's own Google Calendar list.
Needs the service account to have "Make changes and manage sharing" on both calendars.
Only real Google accounts can open a shared calendar.
"""
import os
import sys

from src import calendar_service as cal
from src import db


def main() -> int:
    dry = "--dry-run" in sys.argv
    invite = "--invite" in sys.argv
    if not cal.is_enabled():
        print("Calendar is NOT set up. Check the Google settings in .env first.")
        return 1
    print(f"Service account: {cal.service_account_email() or '(could not read the key)'}")
    emails = [r["email"] for r in db.fetch_employee_emails() if r.get("email")]
    print(f"{len(emails)} employee email(s) found.")
    calendars = {"Holidays": os.getenv("HOLIDAY_CALENDAR_ID"), "Leave": os.getenv("LEAVE_CALENDAR_ID")}
    for name, calendar_id in calendars.items():
        if not calendar_id:
            print(f"{name}: calendar ID not set, skipped.")
            continue
        print(f"{name} subscribe link: {cal.subscribe_link(calendar_id)}")
        if dry:
            mail = " Invitation emails would be sent." if invite else ""
            print(f"{name}: would share with {', '.join(sorted(set(e.lower() for e in emails)))}.{mail}")
            continue
        try:
            out = cal.share_calendar(calendar_id, emails, notify=invite)
        except Exception as e:
            print(f"{name}: FAILED: {e}")
            print("Give the service account 'Make changes and manage sharing' on this calendar.")
            return 1
        print(f"{name}: added {len(out['added'])}, already had access {len(out['skipped'])}, "
              f"failed {len(out['failed'])}")
        for email, reason in out["failed"].items():
            print(f"   {email}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
