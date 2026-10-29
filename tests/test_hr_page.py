"""The HR page, using Streamlit's test runner."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    from src import db, tools

    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("HR_PASSWORD", "hrsecret")
    monkeypatch.setenv("SKIP_KB_SETUP", "1")
    monkeypatch.setattr(db, "fetch_employee",
                        lambda eid: {"employee_id": "EMP001", "name": "Ayesha"} if eid == "EMP001" else None)
    state = {"decisions": [], "pending": [
        {"id": 7, "employee_id": "EMP003", "name": "Sara", "leave_type": "annual",
         "start_date": "2026-11-03", "end_date": "2026-11-05", "working_days": 3, "status": "pending"}],
        "fail": False}

    def listing(statuses, limit=50, newest_first=False):
        if "pending" in statuses:
            return state["pending"]
        return [{"id": 5, "employee_id": "EMP001", "name": "Ayesha", "leave_type": "sick",
                 "start_date": "2026-10-20", "end_date": "2026-10-21", "working_days": 2, "status": "approved"}]

    def decide(request_id, approve):
        state["decisions"].append((request_id, approve))
        if state["fail"]:
            raise RuntimeError("down")
        state["pending"] = []
        return {"ok": True, "message": f"Request #{request_id} approved. The employee was emailed."}

    monkeypatch.setattr(tools, "hr_list_leave_requests", listing)
    monkeypatch.setattr(tools, "decide_leave_request", decide)
    return state


def _hr_login(password="hrsecret"):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[2].set_value(password)
    at.button[1].click().run()
    return at


def _button(at, key):
    return next(b for b in list(at.sidebar.button) + list(at.button) if b.key == key)


def test_wrong_hr_password_is_rejected():
    at = _hr_login("nope")
    assert any("Invalid HR password" in e.value for e in at.error)
    assert "hr_ok" not in at.session_state


def test_the_employee_password_does_not_open_the_hr_page():
    assert any("Invalid HR password" in e.value for e in _hr_login("secret").error)


def test_missing_hr_password_setting_is_reported(monkeypatch):
    monkeypatch.setenv("HR_PASSWORD", "")
    assert any("HR_PASSWORD" in e.value for e in _hr_login("anything").error)


def test_an_employee_login_never_shows_the_hr_page():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value("EMP001")
    at.text_input[1].set_value("secret")
    at.button[0].click().run()
    assert len(at.chat_input) == 1 and "hr_ok" not in at.session_state
    assert not any(b.key and b.key.startswith("approve_") for b in at.button)


def test_hr_sees_pending_requests_and_recent_decisions():
    at = _hr_login()
    assert at.session_state["hr_ok"]
    page = " ".join(m.value for m in at.markdown)
    assert "Request #7: Sara (EMP003)" in page and "#5 Ayesha" in page
    assert _button(at, "approve_7") and _button(at, "reject_7")


def test_approve_calls_the_decision_and_shows_the_result(backend):
    at = _hr_login()
    _button(at, "approve_7").click().run()
    assert backend["decisions"] == [(7, True)]
    assert any("Request #7 approved" in s.value for s in at.success)
    assert any("No pending requests" in i.value for i in at.info)


def test_reject_calls_the_decision(backend):
    at = _hr_login()
    _button(at, "reject_7").click().run()
    assert backend["decisions"] == [(7, False)]


def test_a_failure_shows_a_warning_not_a_crash(backend):
    backend["fail"] = True
    at = _hr_login()
    _button(at, "approve_7").click().run()
    assert any("Something went wrong" in w.value for w in at.warning) and not at.exception


def test_hr_logout_returns_to_login():
    at = _hr_login()
    _button(at, "hr_logout").click().run()
    assert "hr_ok" not in at.session_state


def test_new_requests_show_up_on_the_next_refresh(backend):
    at = _hr_login()
    backend["pending"].append({"id": 8, "employee_id": "EMP001", "name": "Ayesha", "leave_type": "sick",
                               "start_date": "2026-10-30", "end_date": "2026-10-30",
                               "working_days": 1, "status": "pending"})
    at.run()  # what the automatic 10-second reload does
    assert _button(at, "approve_8")


def test_the_page_remembers_which_requests_it_shows():
    at = _hr_login()
    assert at.session_state["hr_seen_ids"] == (7,)  # the invisible 30-second check compares against this
