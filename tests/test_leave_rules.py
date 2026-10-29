"""Leave rules, saving, and the HR decision (tools only, no model)."""
from datetime import date

from src import tools


def d(y, m, day):
    return date(y, m, day)


# ------------------------------------------------------------- the day counter
def test_working_days_skip_weekends_and_holidays():
    # Fri 6 Nov to Tue 10 Nov: Fri, (Sat, Sun), Mon 9 Nov is a holiday, Tue -> 2 days
    assert tools.count_working_days(d(2026, 11, 6), d(2026, 11, 10), {d(2026, 11, 9)}) == 2


def test_a_weekend_has_no_working_days():
    assert tools.count_working_days(d(2026, 11, 7), d(2026, 11, 8), set()) == 0


# ------------------------------------------------------------------ annual leave
def test_annual_leave_ok_with_enough_notice(world):
    r = tools.check_leave_request("EMP001", "annual", d(2026, 11, 3), d(2026, 11, 5))
    assert r["ok"] and r["working_days"] == 3
    assert (r["remaining_before"], r["remaining_after"]) == (14, 11)


def test_annual_leave_needs_three_working_days_notice(world):
    r = tools.check_leave_request("EMP001", "annual", d(2026, 10, 30), d(2026, 10, 30))
    assert not r["ok"] and "3 working days' notice" in r["errors"][0]


def test_long_annual_leave_needs_two_weeks_notice(world):
    # 7 working days starting 10 Nov: less than 14 days away
    r = tools.check_leave_request("EMP001", "annual", d(2026, 11, 10), d(2026, 11, 18))
    assert not r["ok"] and "2 weeks' notice" in r["errors"][0] and "12 Nov 2026" in r["errors"][0]
    # the same length starting 12 Nov is fine
    assert tools.check_leave_request("EMP001", "annual", d(2026, 11, 12), d(2026, 11, 19))["ok"]


def test_annual_leave_cannot_start_in_the_past(world):
    r = tools.check_leave_request("EMP001", "annual", d(2026, 10, 27), d(2026, 10, 28))
    assert not r["ok"] and "past" in r["errors"][0]


def test_holidays_are_not_counted(world):
    r = tools.check_leave_request("EMP001", "annual", d(2026, 11, 6), d(2026, 11, 10))
    assert r["ok"] and r["working_days"] == 2


def test_dates_with_no_working_days_are_rejected(world):
    r = tools.check_leave_request("EMP001", "annual", d(2026, 11, 7), d(2026, 11, 8))
    assert not r["ok"] and "no working days" in r["errors"][0]


def test_end_before_start_is_rejected(world):
    r = tools.check_leave_request("EMP001", "annual", d(2026, 11, 5), d(2026, 11, 3))
    assert not r["ok"] and "before" in r["errors"][0]


def test_unknown_leave_type_is_rejected(world):
    assert not tools.check_leave_request("EMP001", "unpaid", d(2026, 11, 3), d(2026, 11, 3))["ok"]


# ---------------------------------------------------------------------- balance
def test_balance_counts_pending_days(world):
    world.add_request("EMP008", "annual", "2026-12-01", "2026-12-01", 1)  # Hamza: 2 left, 1 pending
    r = tools.check_leave_request("EMP008", "annual", d(2026, 11, 3), d(2026, 11, 4))
    assert not r["ok"]
    assert "1 annual leave days available (1 days are in your pending requests)" in r["errors"][0]


def test_a_pending_sick_request_does_not_reduce_annual_balance(world):
    world.add_request("EMP001", "sick", "2026-12-01", "2026-12-02", 2)
    assert tools.check_leave_request("EMP001", "annual", d(2026, 11, 3), d(2026, 11, 5))["remaining_before"] == 14


# ---------------------------------------------------------------------- overlap
def test_overlap_with_a_pending_or_approved_request(world):
    rid = world.add_request("EMP001", "annual", "2026-11-04", "2026-11-04", 1, status="approved")
    r = tools.check_leave_request("EMP001", "annual", d(2026, 11, 3), d(2026, 11, 5))
    assert not r["ok"] and f"#{rid}" in r["errors"][0]


def test_a_rejected_request_does_not_block(world):
    world.add_request("EMP001", "annual", "2026-11-04", "2026-11-04", 1, status="rejected")
    assert tools.check_leave_request("EMP001", "annual", d(2026, 11, 3), d(2026, 11, 5))["ok"]


def test_other_employees_requests_do_not_overlap(world):
    world.add_request("EMP003", "annual", "2026-11-03", "2026-11-05", 3)
    assert tools.check_leave_request("EMP001", "annual", d(2026, 11, 3), d(2026, 11, 5))["ok"]


# --------------------------------------------------------------------- sick leave
def test_sick_leave_needs_no_notice(world):
    r = tools.check_leave_request("EMP001", "sick", d(2026, 10, 29), d(2026, 10, 30))
    assert r["ok"] and r["working_days"] == 2 and r["notes"] == []


def test_sick_leave_of_three_days_adds_the_certificate_reminder(world):
    r = tools.check_leave_request("EMP001", "sick", d(2026, 10, 29), d(2026, 11, 2))  # Thu, Fri, Mon
    assert r["ok"] and r["working_days"] == 3 and "medical certificate" in r["notes"][0]


def test_sick_leave_cannot_start_long_ago(world):
    r = tools.check_leave_request("EMP001", "sick", d(2026, 10, 20), d(2026, 10, 21))
    assert not r["ok"] and "up to 3 days ago" in r["errors"][0]


def test_sick_balance_is_checked(world):
    # Hamza has 4 sick days left
    r = tools.check_leave_request("EMP008", "sick", d(2026, 10, 29), d(2026, 11, 4))  # 5 working days
    assert not r["ok"] and "4 sick leave days available" in r["errors"][0]


# ------------------------------------------------------------------------ saving
def test_submit_saves_a_pending_request_and_emails_hr(world):
    out = tools.submit_leave_request("EMP003", "annual", d(2026, 11, 3), d(2026, 11, 5))
    assert out["ok"] and out["request_id"] == 1 and out["email_sent"]
    row = world.requests[0]
    assert (row["status"], row["working_days"], row["employee_id"]) == ("pending", 3, "EMP003")
    subject, body, reply_to = world.hr_mails[0]
    assert "[Leave request #1]" in subject and "Sara" in subject
    assert reply_to == "sara@examplecorp.com" and "HR page" in body


def test_submit_checks_the_rules_again(world):
    out = tools.submit_leave_request("EMP003", "annual", d(2026, 10, 30), d(2026, 10, 30))
    assert not out["ok"] and world.requests == [] and world.hr_mails == []


def test_submit_twice_is_blocked_by_the_overlap_rule(world):
    assert tools.submit_leave_request("EMP003", "annual", d(2026, 11, 3), d(2026, 11, 5))["ok"]
    assert not tools.submit_leave_request("EMP003", "annual", d(2026, 11, 3), d(2026, 11, 5))["ok"]
    assert len(world.requests) == 1


def test_database_failure_sends_no_email(world):
    world.fail_insert = True
    out = tools.submit_leave_request("EMP003", "annual", d(2026, 11, 3), d(2026, 11, 5))
    assert not out["ok"] and "could not save" in out["errors"][0] and world.hr_mails == []


# ------------------------------------------------------------------ HR decisions
def _pending(world, days=3):
    return world.add_request("EMP003", "annual", "2026-11-03", "2026-11-05", days)


def test_approve_updates_status_balance_and_emails_the_employee(world):
    rid = _pending(world)
    out = tools.decide_leave_request(rid, True)
    assert out["ok"] and out["status"] == "approved" and out["email_sent"] and out["used_updated"]
    assert world.requests[0]["status"] == "approved"
    assert world.employees["EMP003"]["annual_used"] == 6  # 3 + 3
    address, subject, body = world.employee_mails[0]
    assert address == "sara@examplecorp.com" and "approved" in subject and "3 Nov 2026" in body


def test_reject_does_not_change_the_balance(world):
    rid = _pending(world)
    out = tools.decide_leave_request(rid, False)
    assert out["status"] == "rejected" and world.employees["EMP003"]["annual_used"] == 3
    assert "rejected" in world.employee_mails[0][1]


def test_a_decided_request_cannot_be_decided_again(world):
    rid = _pending(world)
    tools.decide_leave_request(rid, True)
    out = tools.decide_leave_request(rid, False)
    assert not out["ok"] and "already decided" in out["message"]
    assert world.requests[0]["status"] == "approved" and len(world.employee_mails) == 1
    assert world.employees["EMP003"]["annual_used"] == 6  # not added twice


def test_balance_failure_is_reported_to_hr(world):
    rid = _pending(world)
    world.fail_add_used = True
    out = tools.decide_leave_request(rid, True)
    assert out["ok"] and not out["used_updated"] and "balance was not updated" in out["message"]


def test_hr_list_adds_the_employee_name(world):
    _pending(world)
    rows = tools.hr_list_leave_requests(["pending"])
    assert rows[0]["name"] == "Sara"
