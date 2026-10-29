"""HR page: the Escalations tab and the 'Mark as resolved' button."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import db, tools

APP = str(Path(__file__).resolve().parent.parent / "app.py")

ESCALATIONS = [
    {"id": 1042, "employee_id": "EMP003", "question": "My manager is treating me unfairly.",
     "reason": "sensitive topic", "status": "emailed", "created_at": "2026-10-29T10:00:00+00:00"},
]


@pytest.fixture
def hr_app(monkeypatch):
    monkeypatch.setenv("SKIP_KB_SETUP", "1")
    monkeypatch.setenv("APP_PASSWORD", "pw")
    monkeypatch.setenv("HR_PASSWORD", "hrpw")
    state = {"rows": [dict(r) for r in ESCALATIONS]}

    def by_status(statuses, limit=50, newest_first=True):
        return [dict(r) for r in state["rows"] if r["status"] in statuses][:limit]

    def resolve(request_id):
        for r in state["rows"]:
            if r["id"] == request_id and r["status"] != "resolved":
                r["status"] = "resolved"
                return dict(r)
        return None

    monkeypatch.setattr(db, "fetch_escalations_by_status", by_status)
    monkeypatch.setattr(db, "resolve_escalation", resolve)
    monkeypatch.setattr(db, "fetch_leave_requests_by_status", lambda *a, **k: [])
    monkeypatch.setattr(db, "fetch_employee", lambda i: {"employee_id": i, "name": "Sara"})

    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[2].set_value("hrpw")
    at.button[1].click().run()
    assert not at.exception
    return at, state


def test_tabs_and_open_escalation_are_shown(hr_app):
    at, _ = hr_app
    assert [t.label for t in at.tabs][-2:] == ["Leave requests", "Escalations"]
    assert any("HR request #1042" in m.value and "Sara" in m.value for m in at.markdown)
    assert any(b.key == "resolve_1042" for b in at.button)


def test_mark_as_resolved(hr_app):
    at, state = hr_app
    next(b for b in at.button if b.key == "resolve_1042").click().run()
    assert state["rows"][0]["status"] == "resolved"
    assert any("marked as resolved" in s.value for s in at.success)
    assert not any(b.key == "resolve_1042" for b in at.button)


def test_resolving_twice_does_nothing(hr_app):
    _, state = hr_app
    assert tools.resolve_escalation(1042)["ok"]
    again = tools.resolve_escalation(1042)
    assert not again["ok"] and "already resolved" in again["message"]


def test_a_database_error_shows_a_message_not_a_crash(hr_app, monkeypatch):
    at, _ = hr_app

    def broken(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "fetch_escalations_by_status", broken)
    at.run()
    assert not at.exception
    assert any("Could not load the escalations" in e.value for e in at.error)
