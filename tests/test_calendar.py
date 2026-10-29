"""Google Calendar: reading holidays, adding approved leave, and falling back to the holidays table.
A fake calendar service is used, so nothing goes to Google."""
from datetime import date

import pytest

from src import calendar_service as cal
from src import db, tools


class FakeEvents:
    def __init__(self, store):
        self.store = store

    def list(self, calendarId, **kw):
        items = self.store.setdefault(calendarId, [])
        marker = kw.get("privateExtendedProperty")
        if marker:
            key = marker.split("=", 1)[1]
            items = [e for e in items if e.get("extendedProperties", {}).get("private", {}).get("requestId") == key]
        return FakeCall({"items": items})

    def insert(self, calendarId, body):
        event = dict(body, id=f"evt{len(self.store.setdefault(calendarId, [])) + 1}")
        self.store[calendarId].append(event)
        return FakeCall(event)


class FakeCall:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeAcl:
    def __init__(self, rules, fail_for=()):
        self.rules, self.fail_for = rules, fail_for

    def list(self, calendarId, pageToken=None):
        return FakeCall({"items": [{"scope": {"type": "user", "value": e}} for e in self.rules]})

    def insert(self, calendarId, body, sendNotifications=True):
        email = body["scope"]["value"]
        assert body["role"] == "reader" and sendNotifications is False
        if email in self.fail_for:
            raise RuntimeError("not a google account")
        self.rules.append(email)
        return FakeCall({})


class FakeService:
    def __init__(self, store, acl=None):
        self.store = store
        self._acl = acl

    def acl(self):
        return self._acl

    def events(self):
        return FakeEvents(self.store)


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.delenv("DISABLE_CALENDAR", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("HOLIDAY_CALENDAR_ID", "holidays-cal")
    monkeypatch.setenv("LEAVE_CALENDAR_ID", "leave-cal")
    store = {
        "holidays-cal": [
            {"summary": "Foundation Day", "start": {"date": "2026-11-09"}, "end": {"date": "2026-11-10"}},
            {"summary": "Year-End Closure", "start": {"date": "2026-12-30"}, "end": {"date": "2027-01-02"}},
        ]
    }
    monkeypatch.setattr(cal, "_service", lambda: FakeService(store))
    return store


def test_is_enabled_needs_key_and_calendar_id(monkeypatch):
    monkeypatch.delenv("DISABLE_CALENDAR", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("HOLIDAY_CALENDAR_ID", raising=False)
    assert not cal.is_enabled()
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    assert not cal.is_enabled()  # no calendar ID yet
    monkeypatch.setenv("HOLIDAY_CALENDAR_ID", "x")
    assert cal.is_enabled()
    monkeypatch.setenv("DISABLE_CALENDAR", "1")
    assert not cal.is_enabled()


def test_holidays_between_expands_multi_day_events(calendar):
    found = cal.holidays_between(date(2026, 11, 1), date(2027, 1, 5))
    assert found[date(2026, 11, 9)] == "Foundation Day"
    assert sorted(d for d in found if d.month in (12, 1)) == [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 1)]
    assert date(2027, 1, 2) not in found  # the end date of an all-day event is the day after


def test_holiday_rows_have_the_database_shape(calendar):
    rows = cal.holiday_rows_from(date(2026, 11, 1), limit=2)
    assert rows == [{"holiday_date": "2026-11-09", "name": "Foundation Day"},
                    {"holiday_date": "2026-12-30", "name": "Year-End Closure"}]


def test_tools_read_holidays_from_the_calendar(calendar, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the database must not be used when the calendar works")

    monkeypatch.setattr(db, "fetch_holidays_between", boom)
    monkeypatch.setattr(db, "fetch_holiday", boom)
    monkeypatch.setattr(db, "fetch_holidays", boom)
    assert tools._holiday_dates(date(2026, 11, 1), date(2026, 11, 30)) == {date(2026, 11, 9)}
    assert tools.get_holiday(date(2026, 11, 9))["name"] == "Foundation Day"
    assert tools.get_holiday(date(2026, 11, 10)) is None
    assert tools.list_holidays(date(2026, 11, 1), 1)[0]["holiday_date"] == "2026-11-09"


def test_calendar_failure_falls_back_to_the_table(calendar, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("google is down")

    monkeypatch.setattr(cal, "holidays_between", broken)
    monkeypatch.setattr(cal, "holiday_rows_from", broken)
    monkeypatch.setattr(db, "fetch_holidays_between", lambda s, e: [{"holiday_date": "2026-11-09", "name": "T"}])
    monkeypatch.setattr(db, "fetch_holiday", lambda d: {"holiday_date": d, "name": "T"})
    monkeypatch.setattr(db, "fetch_holidays", lambda d, n: [{"holiday_date": "2026-11-09", "name": "T"}])
    assert tools._holiday_dates(date(2026, 11, 1), date(2026, 11, 30)) == {date(2026, 11, 9)}
    assert tools.get_holiday(date(2026, 11, 9))["name"] == "T"
    assert tools.list_holidays(date(2026, 11, 1))[0]["name"] == "T"


def test_not_set_up_uses_the_table(monkeypatch):
    monkeypatch.setenv("DISABLE_CALENDAR", "1")
    monkeypatch.setattr(db, "fetch_holidays_between", lambda s, e: [{"holiday_date": "2026-11-09", "name": "T"}])
    assert tools._holiday_dates(date(2026, 11, 1), date(2026, 11, 30)) == {date(2026, 11, 9)}


def test_add_leave_event_is_all_day_and_not_added_twice(calendar):
    first = cal.add_leave_event("Sara", "EMP003", "annual", date(2026, 11, 3), date(2026, 11, 5), 7)
    again = cal.add_leave_event("Sara", "EMP003", "annual", date(2026, 11, 3), date(2026, 11, 5), 7)
    assert first == again
    events = calendar["leave-cal"]
    assert len(events) == 1
    assert events[0]["start"] == {"date": "2026-11-03"}
    assert events[0]["end"] == {"date": "2026-11-06"}  # the day after the last leave day
    assert events[0]["summary"] == "Sara: on leave"
    # sick leave is private: the leave type is not shown anywhere on the event
    assert "annual" not in events[0]["summary"] + events[0]["description"]


# ------------------------------------------------------------- approval and the calendar
@pytest.fixture
def approval(monkeypatch):
    row = {"id": 7, "employee_id": "EMP003", "leave_type": "annual", "start_date": "2026-11-03",
           "end_date": "2026-11-05", "working_days": 3, "status": "approved"}
    monkeypatch.setattr(db, "decide_leave_request", lambda rid, status: dict(row, status=status))
    monkeypatch.setattr(db, "add_leave_used", lambda *a: None)
    monkeypatch.setattr(db, "fetch_employee", lambda i: {"name": "Sara", "email": "s@x.com"})
    monkeypatch.setattr(tools.emailer, "email_employee", lambda *a, **k: True)


def test_approve_adds_a_calendar_event(calendar, approval):
    result = tools.decide_leave_request(7, True)
    assert result["ok"] and result["calendar_added"] is True
    assert "added to the leave calendar" in result["message"]
    assert len(calendar["leave-cal"]) == 1


def test_reject_adds_nothing(calendar, approval):
    result = tools.decide_leave_request(7, False)
    assert result["ok"] and result["calendar_added"] is None
    assert calendar.get("leave-cal", []) == []


def test_calendar_failure_does_not_undo_the_approval(calendar, approval, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("google is down")

    monkeypatch.setattr(cal, "add_leave_event", broken)
    result = tools.decide_leave_request(7, True)
    assert result["ok"] and result["status"] == "approved"
    assert result["calendar_added"] is False
    assert "could not be added to the leave calendar" in result["message"]


def test_no_calendar_means_the_old_message(approval, monkeypatch):
    monkeypatch.setenv("DISABLE_CALENDAR", "1")
    result = tools.decide_leave_request(7, True)
    assert result["calendar_added"] is None
    assert result["message"] == "Request #7 approved. The employee was emailed."


def test_share_calendar_adds_new_emails_only(monkeypatch):
    acl = FakeAcl(["old@x.com"], fail_for=("bad@x.com",))
    monkeypatch.setattr(cal, "_service", lambda: FakeService({}, acl))
    out = cal.share_calendar("c", ["Old@x.com", "new@x.com", " NEW@x.com ", "bad@x.com", "", None])
    assert out["added"] == ["new@x.com"]
    assert out["skipped"] == ["old@x.com"]
    assert list(out["failed"]) == ["bad@x.com"]
    assert acl.rules == ["old@x.com", "new@x.com"]
