"""Check the Google Calendar setup.   Run from the project root:   python -m scripts.check_calendar

1. Reads the holidays calendar and prints the next holidays.
2. Adds a test event to the leave calendar, then deletes it again.
"""
import sys
from datetime import date, timedelta

from src import calendar_service as cal


def main() -> int:
    if not cal.is_enabled():
        print("Calendar is NOT set up. Check GOOGLE_SERVICE_ACCOUNT_FILE (or _JSON) and HOLIDAY_CALENDAR_ID in .env.")
        return 1
    try:
        rows = cal.holiday_rows_from(date.today(), limit=10)
    except Exception as e:
        print(f"FAILED reading the holidays calendar: {e}")
        print("Check that the calendar is shared with the service account email (Make changes to events).")
        return 1
    print(f"Holidays calendar OK: {len(rows)} upcoming holiday(s)")
    for r in rows:
        print(f"  {r['holiday_date']}  {r['name']}")

    if not cal.leave_calendar_enabled():
        print("LEAVE_CALENDAR_ID is not set, so the write test was skipped.")
        return 0
    try:
        day = date.today() + timedelta(days=60)
        event_id = cal.add_leave_event("Test Person", "TEST", "annual", day, day, 999999)
        print(f"Leave calendar OK: test event created ({event_id})")
        cal._service().events().delete(calendarId=__import__("os").environ["LEAVE_CALENDAR_ID"],
                                       eventId=event_id).execute()
        print("Test event deleted again.")
    except Exception as e:
        print(f"FAILED writing to the leave calendar: {e}")
        print("Check that this calendar is shared with the service account with 'Make changes to events'.")
        return 1
    print("All good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
