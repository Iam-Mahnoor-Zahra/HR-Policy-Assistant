from datetime import date

from src import db, emailer, tools


def _row(**kw):
    base = {"employee_id": "EMP003", "name": "Sara", "email": "sara@examplecorp.com",
            "annual_total": 20, "annual_used": 3, "sick_total": 10, "sick_used": 0}
    base.update(kw)
    return base


# ---------------------------------------------------------------- leave balance
def test_leave_balance_math(monkeypatch):
    monkeypatch.setattr(db, "fetch_employee", lambda eid: _row())
    data = tools.get_leave_balance("EMP003")
    assert data["annual"]["remaining"] == 17
    assert data["sick"]["remaining"] == 10


def test_unknown_employee_returns_none(monkeypatch):
    monkeypatch.setattr(db, "fetch_employee", lambda eid: None)
    assert tools.get_leave_balance("EMP999") is None


# --------------------------------------------------------------- request status
def test_status_asks_the_database_only_for_the_given_employee(monkeypatch):
    seen = {}
    monkeypatch.setattr(db, "fetch_leave_requests", lambda eid, rid=None, limit=5: seen.setdefault("leave", (eid, rid)) and [])
    monkeypatch.setattr(db, "fetch_escalations", lambda eid, rid=None, limit=5: seen.setdefault("hr", (eid, rid)) and [])
    tools.get_request_status("EMP003", request_id=7)
    assert seen["leave"] == ("EMP003", 7)
    assert seen["hr"] == ("EMP003", 7)


def test_status_kind_limits_which_tables_are_read(monkeypatch):
    calls = []
    monkeypatch.setattr(db, "fetch_leave_requests", lambda *a, **k: calls.append("leave") or [])
    monkeypatch.setattr(db, "fetch_escalations", lambda *a, **k: calls.append("hr") or [])
    tools.get_request_status("EMP003", kind="leave")
    assert calls == ["leave"]


# --------------------------------------------------------------------- holidays
def test_holiday_lookup_uses_iso_dates(monkeypatch):
    seen = {}
    monkeypatch.setattr(db, "fetch_holiday", lambda d: seen.setdefault("d", d) and {"name": "Foundation Day"})
    assert tools.get_holiday(date(2026, 11, 9))["name"] == "Foundation Day"
    assert seen["d"] == "2026-11-09"


def test_list_holidays_passes_the_start_day_and_limit(monkeypatch):
    seen = {}
    monkeypatch.setattr(db, "fetch_holidays", lambda d, limit=5: seen.update(d=d, limit=limit) or [])
    tools.list_holidays(date(2026, 10, 27), limit=3)
    assert seen == {"d": "2026-10-27", "limit": 3}


# ------------------------------------------------------------- escalation email
def test_the_draft_is_in_the_employees_voice_and_quotes_their_own_words():
    subject, body = tools.build_escalation_email(
        _row(), "my manager is misbehaving with me", "sensitive topic",
        paragraph="I would like help with how my manager treats me.")
    assert "Sara" in subject and "EMP003" in subject
    assert body.startswith("Dear HR team,")
    assert "I would like help with how my manager treats me." in body
    assert '"my manager is misbehaving with me"' in body       # the original words, unchanged
    assert "sara@examplecorp.com" in body and "Thank you,\nSara" in body
    assert "permission" in body


def test_the_draft_uses_a_plain_paragraph_when_the_model_gave_none():
    _, body = tools.build_escalation_email(_row(), "question", "no source found", paragraph=None)
    assert "could not find an answer" in body


def test_send_escalation_saves_emails_and_marks_it_emailed(monkeypatch):
    status_updates = []
    sent = {}
    monkeypatch.setattr(db, "fetch_employee", lambda eid: _row())
    monkeypatch.setattr(db, "insert_escalation", lambda e, q, r, message=None, status="open": 1042)
    monkeypatch.setattr(db, "update_escalation_status", lambda rid, st: status_updates.append((rid, st)))
    monkeypatch.setattr(emailer, "email_hr", lambda subject, body, reply_to=None: sent.update(
        subject=subject, body=body, reply_to=reply_to) or True)
    info = tools.send_escalation("EMP003", "q", "sensitive topic", "Subject", "Body")
    assert info["request_id"] == 1042 and info["email_sent"] is True
    assert "1042" in sent["subject"] and "Request ID: 1042" in sent["body"]
    assert sent["reply_to"] == "sara@examplecorp.com"
    assert status_updates == [(1042, "emailed")]


def test_if_the_email_fails_the_request_stays_open(monkeypatch):
    status_updates = []
    monkeypatch.setattr(db, "fetch_employee", lambda eid: _row())
    monkeypatch.setattr(db, "insert_escalation", lambda e, q, r, message=None, status="open": 5)
    monkeypatch.setattr(db, "update_escalation_status", lambda rid, st: status_updates.append((rid, st)))
    monkeypatch.setattr(emailer, "email_hr", lambda *a, **k: False)
    info = tools.send_escalation("EMP003", "q", "sensitive topic", "Subject", "Body")
    assert info["request_id"] == 5 and info["email_sent"] is False
    assert status_updates == []


def test_if_saving_fails_the_email_is_still_sent(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(db, "fetch_employee", lambda eid: _row())
    monkeypatch.setattr(db, "insert_escalation", boom)
    monkeypatch.setattr(emailer, "email_hr", lambda *a, **k: True)
    info = tools.send_escalation("EMP003", "q", "sensitive topic", "Subject", "Body")
    assert info["request_id"] is None and info["email_sent"] is True
