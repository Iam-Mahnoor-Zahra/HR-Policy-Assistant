"""A small in-memory fake of the database and the email sender, shared by the leave tests.

Fake "today" is Thursday 29 October 2026. Holidays: 9 Nov 2026 and 25 Dec 2026.
"""
from datetime import date

import pytest

TODAY = date(2026, 10, 29)


class FakeWorld:
    def __init__(self):
        self.employees = {
            "EMP001": {"employee_id": "EMP001", "name": "Ayesha", "email": "ayesha@examplecorp.com",
                       "annual_total": 20, "annual_used": 6, "sick_total": 10, "sick_used": 2},
            "EMP003": {"employee_id": "EMP003", "name": "Sara", "email": "sara@examplecorp.com",
                       "annual_total": 20, "annual_used": 3, "sick_total": 10, "sick_used": 0},
            "EMP008": {"employee_id": "EMP008", "name": "Hamza", "email": "hamza@examplecorp.com",
                       "annual_total": 20, "annual_used": 18, "sick_total": 10, "sick_used": 6},
        }
        self.holidays = ["2026-11-09", "2026-12-25"]
        self.requests = []
        self.hr_mails = []        # (subject, body, reply_to)
        self.employee_mails = []  # (address, subject, body)
        self.fail_insert = False
        self.fail_add_used = False

    def add_request(self, employee_id, leave_type, start, end, days, status="pending"):
        rid = len(self.requests) + 1
        self.requests.append({"id": rid, "employee_id": employee_id, "leave_type": leave_type,
                              "start_date": start, "end_date": end, "working_days": days,
                              "status": status, "created_at": "2026-10-28T09:00:00+00:00"})
        return rid


@pytest.fixture
def world(monkeypatch):
    from src import db, emailer, tools

    w = FakeWorld()
    monkeypatch.setattr(tools, "today", lambda: TODAY)
    monkeypatch.setattr(db, "fetch_employee", lambda eid: dict(w.employees[eid]) if eid in w.employees else None)
    monkeypatch.setattr(db, "fetch_holidays_between",
                        lambda a, b: [{"holiday_date": h, "name": "Holiday"} for h in w.holidays if a <= h <= b])
    monkeypatch.setattr(db, "fetch_pending_leave_requests",
                        lambda eid, lt: [r for r in w.requests if r["employee_id"] == eid
                                         and r["leave_type"] == lt and r["status"] == "pending"])
    monkeypatch.setattr(db, "fetch_overlapping_leave_requests",
                        lambda eid, a, b: [r for r in w.requests if r["employee_id"] == eid
                                           and r["status"] in ("pending", "approved")
                                           and r["start_date"] <= b and r["end_date"] >= a])

    def insert(eid, lt, a, b, days):
        if w.fail_insert:
            raise RuntimeError("database down")
        return w.add_request(eid, lt, a, b, days)

    def decide(rid, status):
        for r in w.requests:
            if r["id"] == rid and r["status"] == "pending":
                r["status"] = status
                return dict(r)
        return None

    def add_used(eid, lt, days):
        if w.fail_add_used:
            raise RuntimeError("database down")
        w.employees[eid][f"{lt}_used"] += days

    monkeypatch.setattr(db, "insert_leave_request", insert)
    monkeypatch.setattr(db, "decide_leave_request", decide)
    monkeypatch.setattr(db, "add_leave_used", add_used)
    monkeypatch.setattr(db, "fetch_leave_requests_by_status",
                        lambda statuses, limit=50, newest_first=False:
                        [dict(r) for r in w.requests if r["status"] in statuses][:limit])
    monkeypatch.setattr(emailer, "hr_email_address", lambda: "hr@examplecorp.com")
    monkeypatch.setattr(emailer, "email_hr",
                        lambda subject, body, reply_to=None: w.hr_mails.append((subject, body, reply_to)) or True)
    monkeypatch.setattr(emailer, "email_employee",
                        lambda address, subject, body: w.employee_mails.append((address, subject, body)) or True)
    return w
