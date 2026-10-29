"""Makes `src` importable and keeps the automatic tests away from the real Google Calendar and Supabase."""
import os

os.environ["DISABLE_CALENDAR"] = "1"  # tests never call Google Calendar unless they switch it on

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_escalation_lists(monkeypatch):
    """The HR page now lists escalations. Tests that do not care get an empty list, not the real database."""
    from src import db

    monkeypatch.setattr(db, "fetch_escalations_by_status", lambda *a, **k: [])
    monkeypatch.setattr(db, "resolve_escalation", lambda *a, **k: None)
