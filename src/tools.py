"""The two tools the agent can use. Both receive the employee ID from our code, never from the model."""
import os

from dotenv import load_dotenv

from src import db

load_dotenv()


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


def escalate(employee_id: str, question: str, reason: str) -> dict:
    """Log the request for HR. If logging fails, still return the HR email so the employee can write."""
    hr_email = os.getenv("HR_EMAIL", "hr@examplecorp.com")
    try:
        request_id = db.insert_escalation(employee_id, question, reason)
    except Exception as e:  # network, keys, table problems
        print(f"[warning] could not log the escalation: {e}")
        request_id = None
    return {"request_id": request_id, "hr_email": hr_email}
