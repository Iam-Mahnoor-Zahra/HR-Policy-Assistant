"""The tools the agent can use. Every tool receives the employee ID from our code (the login),
never from the model."""
import os
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

from src import calendar_service, db, emailer

load_dotenv()

FALLBACK_PARAGRAPH = {
    "sensitive topic": "I would like to raise a concern about a matter at work and ask for HR's help.",
    "no source found": "I have a question that I could not find an answer to in the HR policy documents.",
}
EMAIL_SUBJECT = {
    "sensitive topic": "Request for HR support from {name} ({emp_id})",
    "no source found": "Question for HR from {name} ({emp_id})",
}


# --------------------------------------------------------------- leave balance
def get_employee(employee_id: str):
    return db.fetch_employee(employee_id)


def get_leave_balance(employee_id: str):
    """Look up one employee's leave. Returns None if the employee is not found."""
    row = db.fetch_employee(employee_id)
    if not row:
        return None
    return {
        "name": row["name"],
        "annual": {
            "total": row["annual_total"],
            "used": row["annual_used"],
            "remaining": row["annual_total"] - row["annual_used"],
        },
        "sick": {
            "total": row["sick_total"],
            "used": row["sick_used"],
            "remaining": row["sick_total"] - row["sick_used"],
        },
    }


# -------------------------------------------------------------- request status
def get_request_status(employee_id: str, request_id: int | None = None, kind: str = "any") -> dict:
    """The employee's OWN leave requests and HR requests. Other employees' records are never returned."""
    leave = db.fetch_leave_requests(employee_id, request_id) if kind in ("leave", "any") else []
    hr = db.fetch_escalations(employee_id, request_id) if kind in ("hr", "any") else []
    return {"leave": leave, "hr": hr}


# -------------------------------------------------------------------- holidays
def get_holiday(day: date):
    """The holiday on this day (a row with holiday_date and name), or None.
    Read from Google Calendar; the Supabase table is the backup."""
    if calendar_service.is_enabled():
        try:
            name = calendar_service.holidays_between(day, day).get(day)
            return {"holiday_date": day.isoformat(), "name": name} if name else None
        except Exception as e:
            print(f"[warning] Google Calendar failed, using the holidays table: {e}")
    return db.fetch_holiday(day.isoformat())


def list_holidays(from_day: date, limit: int = 5):
    """The next holidays from a day. Google Calendar first, the Supabase table as backup."""
    if calendar_service.is_enabled():
        try:
            return calendar_service.holiday_rows_from(from_day, limit)
        except Exception as e:
            print(f"[warning] Google Calendar failed, using the holidays table: {e}")
    return db.fetch_holidays(from_day.isoformat(), limit)


# ------------------------------------------------------ escalation with consent
def build_escalation_email(employee: dict, original: str, reason: str, paragraph: str | None = None):
    """Write the draft email, in the employee's voice, that the employee will see before anything is sent.

    `original` is the employee's own message and is quoted word for word, so HR always sees
    exactly what was written. `paragraph` is the model's polite wording of it (or None for a plain one).
    """
    name, emp_id = employee["name"], employee["employee_id"]
    subject = EMAIL_SUBJECT.get(reason, EMAIL_SUBJECT["sensitive topic"]).format(name=name, emp_id=emp_id)
    paragraph = paragraph or FALLBACK_PARAGRAPH.get(reason, FALLBACK_PARAGRAPH["sensitive topic"])
    contact = f" at {employee['email']}" if employee.get("email") else ""
    body = (
        "Dear HR team,\n\n"
        f"{paragraph}\n\n"
        "My original message in the chat was:\n"
        f"\"{original}\"\n\n"
        f"Please contact me{contact}, or reply to this email.\n\n"
        f"Thank you,\n{name}\nEmployee ID: {emp_id}\n\n"
        "(Sent through the HR Policy Assistant with my permission.)"
    )
    return subject, body


def send_escalation(employee_id: str, question: str, reason: str, subject: str, body: str) -> dict:
    """Called ONLY after the employee has said yes to the draft.

    Saves the request, then emails HR with the request ID. If one step fails, the other still happens.
    """
    hr_email = emailer.hr_email_address()
    reply_to = None
    try:
        employee = db.fetch_employee(employee_id)
        reply_to = employee.get("email") if employee else None
    except Exception as e:
        print(f"[warning] could not read the employee record: {e}")

    try:
        request_id = db.insert_escalation(employee_id, question, reason, message=body, status="open")
    except Exception as e:
        print(f"[warning] could not save the escalation: {e}")
        request_id = None

    mail_subject = f"[HR request #{request_id}] {subject}" if request_id else subject
    mail_body = (f"Request ID: {request_id}\n\n" if request_id else "") + body
    sent = emailer.email_hr(mail_subject, mail_body, reply_to=reply_to)

    if request_id and sent:
        try:
            db.update_escalation_status(request_id, "emailed")
        except Exception as e:
            print(f"[warning] could not update the escalation status: {e}")
    return {"request_id": request_id, "email_sent": sent, "hr_email": hr_email}


# =================================================================== leave requests
# Rules from the leave policy. Change the numbers here if the policy changes.
ANNUAL_NOTICE_WORKING_DAYS = 3     # policy 2.2: 3 working days' notice
LONG_LEAVE_WORKING_DAYS = 5        # policy 2.2: more than 5 days in a row ...
LONG_LEAVE_NOTICE_DAYS = 14        # ... needs 2 weeks' notice
CERTIFICATE_FROM_WORKING_DAYS = 3  # policy 3.2: medical certificate from 3 days in a row
SICK_BACKDATE_DAYS = 3             # sick leave may start up to 3 days ago (illness is not planned)
MAX_RANGE_DAYS = 366               # protects the day counter from silly dates


def today() -> date:
    """Today's date in the company time zone (the hosting server runs on UTC, which can be a day behind)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Karachi"))).date()
    except Exception:
        return date.today()


def _holiday_dates(start: date, end: date) -> set:
    """Company holidays between two dates: Google Calendar first, the Supabase table as backup."""
    if calendar_service.is_enabled():
        try:
            return set(calendar_service.holidays_between(start, end))
        except Exception as e:
            print(f"[warning] Google Calendar failed, using the holidays table: {e}")
    rows = db.fetch_holidays_between(start.isoformat(), end.isoformat())
    return {date.fromisoformat(str(r["holiday_date"])[:10]) for r in rows}


def count_working_days(start: date, end: date, holidays: set) -> int:
    """Days from start to end (both included), skipping weekends and holidays."""
    total, day = 0, start
    while day <= end:
        if day.weekday() < 5 and day not in holidays:
            total += 1
        day += timedelta(days=1)
    return total


def _fmt(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"  # no %-d, so it also works on Windows


def check_leave_request(employee_id: str, leave_type: str, start: date, end: date) -> dict:
    """Check every rule. Nothing is saved here.

    Returns {"ok", "errors": [...], "notes": [...], "working_days", "pending_days",
             "remaining_before", "remaining_after"}. The code decides, never the model.
    """
    result = {"ok": False, "errors": [], "notes": [], "working_days": 0, "pending_days": 0,
              "remaining_before": 0, "remaining_after": 0}
    errors, notes = result["errors"], result["notes"]

    if leave_type not in ("annual", "sick"):
        errors.append("I can only take annual or sick leave requests.")
        return result
    employee = db.fetch_employee(employee_id)
    if employee is None:
        errors.append("I could not find your employee record.")
        return result
    if end < start:
        errors.append("The end date is before the start date.")
        return result
    if (end - start).days > MAX_RANGE_DAYS:
        errors.append("That date range is too long. Please ask for a shorter period.")
        return result

    now = today()
    if leave_type == "annual" and start < now:
        errors.append("Annual leave cannot start in the past.")
    if leave_type == "sick" and start < now - timedelta(days=SICK_BACKDATE_DAYS):
        errors.append(f"Sick leave can only start up to {SICK_BACKDATE_DAYS} days ago. Please contact HR.")
    if errors:
        return result

    holidays = _holiday_dates(min(now, start), end)
    days = count_working_days(start, end, holidays)
    result["working_days"] = days
    if days == 0:
        errors.append("These dates have no working days (weekends and company holidays are not counted).")
        return result

    # balance, including days that are still waiting for HR
    pending_days = sum(r["working_days"] for r in db.fetch_pending_leave_requests(employee_id, leave_type))
    remaining = employee[f"{leave_type}_total"] - employee[f"{leave_type}_used"] - pending_days
    result.update(pending_days=pending_days, remaining_before=remaining, remaining_after=remaining - days)
    if days > remaining:
        extra = f" ({pending_days} days are in your pending requests)" if pending_days else ""
        errors.append(f"You have {remaining} {leave_type} leave days available{extra}, "
                      f"but this request needs {days}.")

    # no overlap with another request
    for r in db.fetch_overlapping_leave_requests(employee_id, start.isoformat(), end.isoformat()):
        errors.append(
            f"This overlaps with your {r['leave_type']} leave request #{r['id']} "
            f"({_fmt(date.fromisoformat(str(r['start_date'])[:10]))} to "
            f"{_fmt(date.fromisoformat(str(r['end_date'])[:10]))}, {r['status']})."
        )

    if leave_type == "annual" and start >= now:
        if days > LONG_LEAVE_WORKING_DAYS:
            earliest = now + timedelta(days=LONG_LEAVE_NOTICE_DAYS)
            if start < earliest:
                errors.append(
                    f"Annual leave of more than {LONG_LEAVE_WORKING_DAYS} working days needs at least "
                    f"2 weeks' notice. The earliest start date is {_fmt(earliest)}."
                )
        else:
            # working days from today up to the day before the leave starts
            notice = count_working_days(now, start - timedelta(days=1), holidays) if start > now else 0
            if notice < ANNUAL_NOTICE_WORKING_DAYS:
                errors.append(
                    f"Annual leave needs at least {ANNUAL_NOTICE_WORKING_DAYS} working days' notice. "
                    f"This request gives {notice}."
                )

    if leave_type == "sick" and days >= CERTIFICATE_FROM_WORKING_DAYS:
        notes.append(
            f"Sick leave of {CERTIFICATE_FROM_WORKING_DAYS} or more working days in a row needs a "
            "medical certificate. Please give it to HR within 2 days of your return."
        )
    result["ok"] = not errors
    return result


def submit_leave_request(employee_id: str, leave_type: str, start: date, end: date) -> dict:
    """Called ONLY after the employee has said yes. The rules are checked again before saving."""
    check = check_leave_request(employee_id, leave_type, start, end)
    out = {"ok": False, "errors": check["errors"], "request_id": None, "email_sent": False,
           "working_days": check["working_days"]}
    if not check["ok"]:
        return out
    try:
        request_id = db.insert_leave_request(
            employee_id, leave_type, start.isoformat(), end.isoformat(), check["working_days"]
        )
    except Exception as e:
        print(f"[error] could not save the leave request: {e}")
        out["errors"] = ["I could not save your request. Please try again, or email HR."]
        return out

    employee = db.fetch_employee(employee_id) or {}
    subject = (f"[Leave request #{request_id}] {leave_type.capitalize()} leave: "
               f"{employee.get('name', employee_id)} ({employee_id})")
    body = (
        f"{employee.get('name', employee_id)} ({employee_id}) has requested {leave_type} leave.\n\n"
        f"Request ID: {request_id}\n"
        f"Dates: {_fmt(start)} to {_fmt(end)}\n"
        f"Working days: {check['working_days']}\n"
        f"Balance after approval: {check['remaining_after']} {leave_type} days\n\n"
        "Please approve or reject it on the HR page."
    )
    if check["notes"]:
        body += "\n\n" + " ".join(check["notes"])
    out.update(ok=True, request_id=request_id, errors=[],
               email_sent=emailer.email_hr(subject, body, reply_to=employee.get("email")))
    return out


# ------------------------------------------------------------------- the HR page
def hr_list_leave_requests(statuses: list, limit: int = 50, newest_first: bool = False) -> list:
    """Requests of all employees with the employee name added. For the HR page only."""
    rows = db.fetch_leave_requests_by_status(statuses, limit, newest_first)
    names = {}
    for r in rows:
        emp_id = r["employee_id"]
        if emp_id not in names:
            emp = db.fetch_employee(emp_id) or {}
            names[emp_id] = emp.get("name", emp_id)
        r["name"] = names[emp_id]
    return rows


def decide_leave_request(request_id: int, approve: bool) -> dict:
    """HR approves or rejects a pending request. Approved days are added to the used total,
    and the employee is told by email. A request that was already decided is left alone."""
    status = "approved" if approve else "rejected"
    row = db.decide_leave_request(request_id, status)
    if row is None:
        return {"ok": False, "status": None, "email_sent": False, "used_updated": False,
                "message": f"Request #{request_id} was already decided, or it does not exist."}

    used_updated = True
    if approve:
        try:
            db.add_leave_used(row["employee_id"], row["leave_type"], row["working_days"])
        except Exception as e:
            print(f"[warning] could not update the used leave days: {e}")
            used_updated = False

    employee = db.fetch_employee(row["employee_id"]) or {}
    start = date.fromisoformat(str(row["start_date"])[:10])
    end = date.fromisoformat(str(row["end_date"])[:10])

    # approved leave goes on the shared calendar; a calendar problem never undoes the approval
    calendar_added = None  # None = calendar not set up
    if approve and calendar_service.leave_calendar_enabled():
        try:
            calendar_service.add_leave_event(
                employee.get("name", row["employee_id"]), row["employee_id"], row["leave_type"],
                start, end, request_id,
            )
            calendar_added = True
        except Exception as e:
            print(f"[warning] could not add the leave to Google Calendar: {e}")
            calendar_added = False
    email_sent = False
    if employee.get("email"):
        email_sent = emailer.email_employee(
            employee["email"],
            f"Your {row['leave_type']} leave request #{request_id} was {status}",
            f"Dear {employee.get('name', '')},\n\n"
            f"Your {row['leave_type']} leave request #{request_id} "
            f"({_fmt(start)} to {_fmt(end)}, {row['working_days']} working days) was {status} by HR.\n\n"
            "You can ask the HR Policy Assistant for the status of your requests at any time.\n\n"
            "HR team",
        )
    message = f"Request #{request_id} {status}. " + (
        "The employee was emailed." if email_sent else "The employee could not be emailed."
    )
    if not used_updated:
        message += " Warning: the leave balance was not updated, please check it."
    if calendar_added is True:
        message += " It was added to the leave calendar."
    elif calendar_added is False:
        message += " Warning: it could not be added to the leave calendar, please add it by hand."
    return {"ok": True, "status": status, "email_sent": email_sent, "used_updated": used_updated,
            "calendar_added": calendar_added, "message": message}


# ------------------------------------------------------- the HR page: escalations
def hr_list_escalations(statuses: list, limit: int = 50, newest_first: bool = True) -> list:
    """Escalations of all employees with the employee name added. For the HR page only."""
    rows = db.fetch_escalations_by_status(statuses, limit, newest_first)
    names = {}
    for r in rows:
        emp_id = r["employee_id"]
        if emp_id not in names:
            emp = db.fetch_employee(emp_id) or {}
            names[emp_id] = emp.get("name", emp_id)
        r["name"] = names[emp_id]
    return rows


def resolve_escalation(request_id: int) -> dict:
    """HR marks an escalation as resolved. One that is already resolved is left alone."""
    row = db.resolve_escalation(request_id)
    if row is None:
        return {"ok": False, "message": f"HR request #{request_id} was already resolved, or it does not exist."}
    return {"ok": True, "message": f"HR request #{request_id} marked as resolved."}
