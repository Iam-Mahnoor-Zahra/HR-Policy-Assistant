from src import db, tools


def _row(**kw):
    base = {"employee_id": "EMP003", "name": "Sara", "annual_total": 20, "annual_used": 3,
            "sick_total": 10, "sick_used": 0}
    base.update(kw)
    return base


def test_leave_balance_math(monkeypatch):
    monkeypatch.setattr(db, "fetch_employee", lambda eid: _row())
    data = tools.get_leave_balance("EMP003")
    assert data["annual"]["remaining"] == 17
    assert data["sick"]["remaining"] == 10


def test_unknown_employee_returns_none(monkeypatch):
    monkeypatch.setattr(db, "fetch_employee", lambda eid: None)
    assert tools.get_leave_balance("EMP999") is None


def test_escalate_returns_request_id_and_email(monkeypatch):
    monkeypatch.setattr(db, "insert_escalation", lambda e, q, r: 1042)
    info = tools.escalate("EMP001", "question", "sensitive topic")
    assert info["request_id"] == 1042
    assert "@" in info["hr_email"]


def test_escalate_still_returns_email_if_logging_fails(monkeypatch):
    def boom(*args):
        raise RuntimeError("database down")

    monkeypatch.setattr(db, "insert_escalation", boom)
    info = tools.escalate("EMP001", "question", "no source found")
    assert info["request_id"] is None
    assert "@" in info["hr_email"]
