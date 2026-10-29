"""Share both calendars (read only) with every employee email in the Supabase employees table.

Run from the project root:
    python -m scripts.share_calendars --dry-run     (only shows who would get access)
    python -m scripts.share_calendars               (does it)

Safe to run again: emails that already have access are skipped. No invitation emails are sent.
Needs the service account to have "Make changes and manage sharing" on both calendars.
Only real Google accounts can open a shared calendar.
"""
import os
import sys

from src import calendar_service as cal
from src import db


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not cal.is_enabled():
        print("Calendar is NOT set up. Check the Google settings in .env first.")
        return 1
    emails = [r["email"] for r in db.fetch_employee_emails() if r.get("email")]
    print(f"{len(emails)} employee email(s) found.")
    calendars = {"Holidays": os.getenv("HOLIDAY_CALENDAR_ID"), "Leave": os.getenv("LEAVE_CALENDAR_ID")}
    for name, calendar_id in calendars.items():
        if not calendar_id:
            print(f"{name}: calendar ID not set, skipped.")
            continue
        if dry:
            print(f"{name}: would share with {', '.join(sorted(set(e.lower() for e in emails)))}")
            continue
        try:
            out = cal.share_calendar(calendar_id, emails)
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
