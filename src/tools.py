"""The tools the agent can use. Every tool receives the employee ID from our code (the login),
never from the model."""
from datetime import date

from dotenv import load_dotenv

from src import db, emailer

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
    return db.fetch_holiday(day.isoformat())


def list_holidays(from_day: date, limit: int = 5):
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
