"""Google Calendar: read company holidays, and add approved leave.

Settings (environment or hosting secrets):
  GOOGLE_SERVICE_ACCOUNT_JSON   the whole JSON key as text (hosting)
  GOOGLE_SERVICE_ACCOUNT_FILE   or the path of the JSON key file (your laptop)
  HOLIDAY_CALENDAR_ID           calendar "ExampleCorp Holidays" (read)
  LEAVE_CALENDAR_ID             calendar "ExampleCorp Leave" (write)

Nothing here raises when the calendar is not set up: is_enabled() is False and the callers
use the Supabase holidays table instead. Real errors are raised, and the callers decide what to do.
"""
import base64
import json
import os
from datetime import date, timedelta
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEOUT_SECONDS = 15


def is_enabled() -> bool:
    """True only when the key and the calendar IDs are set. DISABLE_CALENDAR=1 switches it off (tests)."""
    if os.getenv("DISABLE_CALENDAR") == "1":
        return False
    has_key = bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"))
    return has_key and bool(os.getenv("HOLIDAY_CALENDAR_ID"))


def leave_calendar_enabled() -> bool:
    return is_enabled() and bool(os.getenv("LEAVE_CALENDAR_ID"))


def _load_key() -> dict:
    text = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if text:
        return json.loads(text)
    with open(os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _service():
    """The Google Calendar client (built once)."""
    import google_auth_httplib2
    import httplib2
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(_load_key(), scopes=SCOPES)
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=TIMEOUT_SECONDS))
    return build("calendar", "v3", http=http, cache_discovery=False)


def _events(calendar_id: str, start: date, end: date) -> list:
    """All events that touch start..end (both included)."""
    service = _service()
    items, token = [], None
    while True:
        res = service.events().list(
            calendarId=calendar_id,
            timeMin=f"{start.isoformat()}T00:00:00Z",
            timeMax=f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
            pageToken=token,
        ).execute()
        items.extend(res.get("items", []))
        token = res.get("nextPageToken")
        if not token:
            return items


def holidays_between(start: date, end: date) -> dict:
    """{date: name} for every holiday day between start and end. A multi-day event gives one entry per day."""
    found = {}
    for ev in _events(os.environ["HOLIDAY_CALENDAR_ID"], start, end):
        if ev.get("status") == "cancelled":
            continue
        first = ev.get("start", {})
        last = ev.get("end", {})
        if "date" in first:  # all-day event: the end date is the day AFTER the last day
            day = date.fromisoformat(first["date"])
            stop = date.fromisoformat(last.get("date", first["date"]))
            if stop <= day:
                stop = day + timedelta(days=1)
        elif "dateTime" in first:  # a timed event counts for its start day
            day = date.fromisoformat(first["dateTime"][:10])
            stop = day + timedelta(days=1)
        else:
            continue
        while day < stop:
            if start <= day <= end:
                found.setdefault(day, ev.get("summary", "Holiday"))
            day += timedelta(days=1)
    return found


def holiday_rows_from(from_day: date, limit: int = 5, look_ahead_days: int = 400) -> list:
    """The next holidays from a day, as rows shaped like the database rows:
    [{"holiday_date": "2026-12-25", "name": "..."}]."""
    found = holidays_between(from_day, from_day + timedelta(days=look_ahead_days))
    return [{"holiday_date": d.isoformat(), "name": found[d]} for d in sorted(found)][:limit]


def add_leave_event(employee_name: str, employee_id: str, leave_type: str, start: date, end: date,
                    request_id: int) -> str:
    """Add an all-day event for approved leave. Returns the event ID.

    If an event for this request already exists, it is not added twice.
    """
    service = _service()
    calendar_id = os.environ["LEAVE_CALENDAR_ID"]
    marker = f"leave-request-{request_id}"
    existing = service.events().list(
        calendarId=calendar_id, privateExtendedProperty=f"requestId={marker}", maxResults=1
    ).execute().get("items", [])
    if existing:
        return existing[0]["id"]

    body = {
        # the leave type is left out on purpose: sick leave is private, and everyone can see this calendar
        "summary": f"{employee_name}: on leave",
        "description": f"{employee_name} ({employee_id}), request #{request_id}. "
                       "Added automatically when HR approved the request.",
        "start": {"date": start.isoformat()},
        "end": {"date": (end + timedelta(days=1)).isoformat()},  # Google wants the day after the last day
        "transparency": "transparent",
        "extendedProperties": {"private": {"requestId": marker}},
    }
    return service.events().insert(calendarId=calendar_id, body=body).execute()["id"]


def subscribe_link(calendar_id: str) -> str:
    """The link that adds a calendar to a person's own Google Calendar list (they must be signed in
    with an account that has access)."""
    cid = base64.b64encode(calendar_id.encode()).decode().rstrip("=")
    return f"https://calendar.google.com/calendar/u/0?cid={cid}"


def service_account_email() -> str:
    """The service account's email address, or an empty text when the key cannot be read."""
    try:
        return _load_key().get("client_email", "")
    except Exception:
        return ""


def share_calendar(calendar_id: str, emails: list, notify: bool = False) -> dict:
    """Give each email read-only access to a calendar. Emails that already have access are skipped.

    Returns {"added": [...], "skipped": [...], "failed": {email: reason}}.
    By default no invitation emails are sent. With notify=True, Google emails each NEWLY added person
    an invitation (people who already had access get nothing).
    The service account needs "Make changes and manage sharing" on the calendar.
    """
    service = _service()
    have, token = set(), None
    while True:
        res = service.acl().list(calendarId=calendar_id, pageToken=token).execute()
        for rule in res.get("items", []):
            if rule.get("scope", {}).get("type") == "user":
                have.add(rule["scope"]["value"].lower())
        token = res.get("nextPageToken")
        if not token:
            break

    out = {"added": [], "skipped": [], "failed": {}}
    for email in sorted({e.strip().lower() for e in emails if e and e.strip()}):
        if email in have:
            out["skipped"].append(email)
            continue
        try:
            service.acl().insert(
                calendarId=calendar_id,
                body={"role": "reader", "scope": {"type": "user", "value": email}},
                sendNotifications=bool(notify),
            ).execute()
            out["added"].append(email)
        except Exception as e:
            out["failed"][email] = str(e)[:120]
    return out
