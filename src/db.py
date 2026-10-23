"""Supabase access: the only place that talks to the database."""
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def get_client():
    from supabase import create_client  # imported here so tests can run without it

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def fetch_employee(employee_id: str):
    """Return the employee row as a dict, or None if the ID does not exist."""
    res = (
        get_client()
        .table("employees")
        .select("*")
        .eq("employee_id", employee_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def insert_escalation(employee_id: str, question: str, reason: str):
    """Save an escalation row and return its request ID."""
    res = (
        get_client()
        .table("escalations")
        .insert({"employee_id": employee_id, "question": question, "reason": reason})
        .execute()
    )
    return res.data[0]["id"]
