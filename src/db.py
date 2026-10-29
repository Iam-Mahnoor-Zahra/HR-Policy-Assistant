"""Supabase access: the only place that talks to the database."""
import os
from datetime import datetime, timezone
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


# ---------------------------------------------------- leave requests: saving and rules
def insert_leave_request(employee_id: str, leave_type: str, start_iso: str, end_iso: str,
                         working_days: int):
    """Save a new leave request as pending and return its ID."""
    row = {
        "employee_id": employee_id,
        "leave_type": leave_type,
        "start_date": start_iso,
        "end_date": end_iso,
        "working_days": working_days,
        "status": "pending",
    }
    res = _table("leave_requests").insert(row).execute()
    return res.data[0]["id"]


def fetch_pending_leave_requests(employee_id: str, leave_type: str):
    """The employee's own pending requests of one leave type (their days count against the balance)."""
    res = (
        _table("leave_requests").select("*")
        .eq("employee_id", employee_id).eq("leave_type", leave_type).eq("status", "pending")
        .execute()
    )
    return res.data


def fetch_overlapping_leave_requests(employee_id: str, start_iso: str, end_iso: str):
    """The employee's own pending or approved requests that touch the given dates."""
    res = (
        _table("leave_requests").select("*")
        .eq("employee_id", employee_id)
        .in_("status", ["pending", "approved"])
        .lte("start_date", end_iso).gte("end_date", start_iso)
        .execute()
    )
    return res.data


def fetch_holidays_between(start_iso: str, end_iso: str):
    res = (
        _table("holidays").select("*")
        .gte("holiday_date", start_iso).lte("holiday_date", end_iso)
        .order("holiday_date").execute()
    )
    return res.data


# ----------------------------------------------------------------- HR page only
def fetch_leave_requests_by_status(statuses: list, limit: int = 50, newest_first: bool = False):
    """Requests of ALL employees. Only the HR page may call this (never the employee chat)."""
    column = "decided_at" if newest_first else "created_at"
    q = _table("leave_requests").select("*").in_("status", statuses)
    return q.order(column, desc=newest_first).limit(limit).execute().data


def decide_leave_request(request_id: int, status: str):
    """Set approved or rejected, but only if the request is still pending.

    Returns the updated row, or None if it was already decided (so a double click does nothing).
    """
    res = (
        _table("leave_requests")
        .update({"status": status, "decided_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", request_id).eq("status", "pending")
        .execute()
    )
    return res.data[0] if res.data else None


def add_leave_used(employee_id: str, leave_type: str, days: int):
    """Add approved days to the employee's used total."""
    if leave_type not in ("annual", "sick"):
        raise ValueError("leave_type must be annual or sick")
    column = f"{leave_type}_used"
    row = fetch_employee(employee_id)
    _table("employees").update({column: row[column] + days}).eq("employee_id", employee_id).execute()


# --------------------------------------------------------------- saved chat history
def insert_chat(employee_id: str, title: str, messages: list):
    """Save a new chat for one employee and return its ID."""
    row = {"employee_id": employee_id, "title": title, "messages": messages}
    return _table("chat_sessions").insert(row).execute().data[0]["id"]


def update_chat(chat_id: int, employee_id: str, title: str, messages: list):
    """Update a chat. The employee ID is part of the filter, so nobody can overwrite another's chat."""
    (
        _table("chat_sessions")
        .update({"title": title, "messages": messages, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", chat_id).eq("employee_id", employee_id)
        .execute()
    )


def fetch_chats(employee_id: str, limit: int = 30):
    """The employee's OWN saved chats, most recently used first."""
    res = (
        _table("chat_sessions").select("id, title, messages")
        .eq("employee_id", employee_id)
        .order("updated_at", desc=True).limit(limit)
        .execute()
    )
    return res.data


def fetch_escalations_by_status(statuses: list, limit: int = 50, newest_first: bool = True):
    """Escalations of ALL employees. Only the HR page may call this (never the employee chat)."""
    q = _table("escalations").select("*").in_("status", statuses)
    return q.order("created_at", desc=newest_first).limit(limit).execute().data


def resolve_escalation(request_id: int):
    """Set resolved, but only if it is not resolved yet. Returns the row, or None if nothing changed."""
    res = (
        _table("escalations").update({"status": "resolved"})
        .eq("id", request_id).neq("status", "resolved")
        .execute()
    )
    return res.data[0] if res.data else None


def fetch_employee_emails():
    """Name and email of every employee. Only for the calendar sharing script, never the employee chat."""
    return _table("employees").select("employee_id, name, email").execute().data
