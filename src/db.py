"""Supabase access: the only place that talks to the database."""
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def get_client():
    from supabase import create_client  # imported here so tests can run without it

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _table(name: str):
    return get_client().table(name)


# ----------------------------------------------------------------- employees
def fetch_employee(employee_id: str):
    """Return the employee row as a dict, or None if the ID does not exist."""
    res = _table("employees").select("*").eq("employee_id", employee_id).limit(1).execute()
    return res.data[0] if res.data else None


# ---------------------------------------------------------------- escalations
def insert_escalation(employee_id: str, question: str, reason: str, message: str | None = None,
                      status: str = "open"):
    """Save an escalation row and return its request ID."""
    row = {"employee_id": employee_id, "question": question, "reason": reason, "status": status}
    if message is not None:
        row["message"] = message
    res = _table("escalations").insert(row).execute()
    return res.data[0]["id"]


def update_escalation_status(request_id: int, status: str):
    _table("escalations").update({"status": status}).eq("id", request_id).execute()


def fetch_escalations(employee_id: str, request_id: int | None = None, limit: int = 5):
    """The employee's own escalations, newest first."""
    q = _table("escalations").select("*").eq("employee_id", employee_id)
    if request_id is not None:
        q = q.eq("id", request_id)
    return q.order("created_at", desc=True).limit(limit).execute().data


# ------------------------------------------------------------- leave requests
def fetch_leave_requests(employee_id: str, request_id: int | None = None, limit: int = 5):
    """The employee's own leave requests, newest first."""
    q = _table("leave_requests").select("*").eq("employee_id", employee_id)
    if request_id is not None:
        q = q.eq("id", request_id)
    return q.order("created_at", desc=True).limit(limit).execute().data


# ------------------------------------------------------------------- holidays
def fetch_holiday(day_iso: str):
    res = _table("holidays").select("*").eq("holiday_date", day_iso).limit(1).execute()
    return res.data[0] if res.data else None


def fetch_holidays(from_day_iso: str, limit: int = 5):
    res = (
        _table("holidays")
        .select("*")
        .gte("holiday_date", from_day_iso)
        .order("holiday_date")
        .limit(limit)
        .execute()
    )
    return res.data
