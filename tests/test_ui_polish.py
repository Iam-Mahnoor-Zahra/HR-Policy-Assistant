"""UI polish: no sidebar on the HR page, the Approving... spinner, the double-click guard, the SVG icon,
and the calendar subscribe link / invitation flag."""
import base64
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import calendar_service as cal
from src import db, tools

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
APP = str(APP_PATH)

PENDING = [{"id": 5, "employee_id": "EMP003", "name": "Sara", "leave_type": "annual",
            "start_date": "2026-11-03", "end_date": "2026-11-05", "working_days": 3, "status": "pending"}]


@pytest.fixture
def hr_app(monkeypatch):
    monkeypatch.setenv("SKIP_KB_SETUP", "1")
    monkeypatch.setenv("APP_PASSWORD", "pw")
    monkeypatch.setenv("HR_PASSWORD", "hrpw")
    calls = []

    def list_requests(statuses, limit=50, newest_first=False):
        return [dict(r) for r in PENDING] if "pending" in statuses else []

    def decide(request_id, approve):
        calls.append((request_id, approve))
        return {"ok": True, "status": "approved", "message": f"Request #{request_id} approved."}

    monkeypatch.setattr(tools, "hr_list_leave_requests", list_requests)
    monkeypatch.setattr(tools, "hr_list_escalations", lambda *a, **k: [])
    monkeypatch.setattr(tools, "decide_leave_request", decide)
    monkeypatch.setattr(db, "fetch_employee", lambda i: {"employee_id": i, "name": "Sara"})

    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[2].set_value("hrpw")
    at.button[1].click().run()
    assert not at.exception
    return at, calls


def test_hr_page_has_no_sidebar_and_keeps_its_contract(hr_app):
    at, _ = hr_app
    assert len(at.sidebar.children) == 0
    assert at.title[0].value == "HR page"
    assert any(b.key == "hr_logout" for b in at.button)
    assert [t.label for t in at.tabs][-2:] == ["Leave requests", "Escalations"]


def test_approve_works_and_shows_the_notice(hr_app):
    at, calls = hr_app
    next(b for b in at.button if b.key == "approve_5").click().run()
    assert calls == [(5, True)]
    assert any("Request #5 approved" in s.value for s in at.success)


def test_a_second_click_on_the_same_request_is_ignored(hr_app):
    at, calls = hr_app
    next(b for b in at.button if b.key == "approve_5").click().run()
    # the fake still lists the request as pending, as if the page had not refreshed yet
    assert any(b.key == "approve_5" for b in at.button)
    next(b for b in at.button if b.key == "approve_5").click().run()
    assert calls == [(5, True)]
    assert not at.warning  # no 'already decided' message over the real result


def test_no_emoji_icon_is_left_in_the_app():
    assert "🤖" not in APP_PATH.read_text(encoding="utf-8")
    assert (APP_PATH.parent / "assets" / "icon.png").exists()


def test_employee_chat_still_works_with_the_new_sidebar(monkeypatch):
    monkeypatch.setenv("SKIP_KB_SETUP", "1")
    monkeypatch.setenv("APP_PASSWORD", "pw")
    monkeypatch.setattr(db, "fetch_employee", lambda i: {"employee_id": i, "name": "Sara"})
    monkeypatch.setattr(db, "fetch_chats", lambda *a, **k: [])
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("EMP003")
    at.text_input[1].set_value("pw")
    at.button[0].click().run()
    assert not at.exception
    assert any(b.key == "new_chat" for b in at.sidebar.button)
    assert any(b.key == "logout" for b in at.sidebar.button)


# ---------------------------------------------------------------- calendar sharing
def test_subscribe_link_holds_the_calendar_id():
    link = cal.subscribe_link("abc123@group.calendar.google.com")
    assert link.startswith("https://calendar.google.com/calendar/u/0?cid=")
    cid = link.split("cid=")[1]
    assert base64.b64decode(cid + "=" * (-len(cid) % 4)).decode() == "abc123@group.calendar.google.com"


class FakeAcl:
    def __init__(self):
        self.inserted = []

    def list(self, calendarId, pageToken=None):
        return type("R", (), {"execute": lambda self: {"items": [{"scope": {"type": "user", "value": "old@x.com"}}]}})()

    def insert(self, calendarId, body, sendNotifications):
        self.inserted.append((body["scope"]["value"], sendNotifications))
        return type("R", (), {"execute": lambda self: {}})()


class FakeService:
    def __init__(self):
        self._acl = FakeAcl()

    def acl(self):
        return self._acl


@pytest.mark.parametrize("notify", [False, True])
def test_invitation_emails_only_when_asked(monkeypatch, notify):
    service = FakeService()
    monkeypatch.setattr(cal, "_service", lambda: service)
    kwargs = {"notify": True} if notify else {}
    out = cal.share_calendar("cal-id", ["New@x.com", "old@x.com"], **kwargs)
    assert out["added"] == ["new@x.com"] and out["skipped"] == ["old@x.com"]
    assert service._acl.inserted == [("new@x.com", notify)]
