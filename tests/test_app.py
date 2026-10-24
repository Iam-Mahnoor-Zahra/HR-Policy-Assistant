"""Tests for the Streamlit app, using Streamlit's built-in test runner (no browser needed)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    from src import agent, db

    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("SKIP_KB_SETUP", "1")
    monkeypatch.setattr(
        db, "fetch_employee",
        lambda eid: {"employee_id": "EMP001", "name": "Ayesha"} if eid == "EMP001" else None,
    )
    calls = []

    def fake_run_agent(employee_id, question, history=None):
        calls.append((employee_id, question, history))
        return {
            "reply": "Up to 5 days.\nSource: Leave Policy, Section 4.2 (Carry-forward limit)",
            "path": "policy",
            "request_id": None,
            "citations": [{
                "label": "Leave Policy, Section 4.2 (Carry-forward limit)",
                "policy": "Leave Policy", "section": "4.2", "title": "Carry-forward limit",
                "file": "leave_policy.md", "path": "data/policies/leave_policy.md",
                "excerpt": "Employees may carry forward up to 5 days.",
            }],
        }

    monkeypatch.setattr(agent, "run_agent", fake_run_agent)
    return calls


def _login(at, employee_id="EMP001", password="secret"):
    at.text_input[0].set_value(employee_id)
    at.text_input[1].set_value(password)
    at.button[0].click().run()
    return at


def _logged_in():
    return _login(AppTest.from_file(APP).run())


def _button(at, key):
    everything = list(at.sidebar.button) + list(at.button)
    return next(b for b in everything if b.key == key)


def test_wrong_password_is_rejected():
    at = _login(AppTest.from_file(APP).run(), password="wrong")
    assert any("Invalid employee ID or password" in e.value for e in at.error)
    assert len(at.chat_input) == 0


def test_unknown_employee_is_rejected():
    at = _login(AppTest.from_file(APP).run(), employee_id="EMP999")
    assert any("Invalid employee ID or password" in e.value for e in at.error)


def test_login_starts_with_one_empty_chat():
    at = _logged_in()
    assert len(at.chat_input) == 1
    assert at.session_state["employee"]["id"] == "EMP001"
    assert len(at.session_state["chats"]) == 1


def test_a_question_is_answered_titled_and_remembered(fake_backend):
    at = _logged_in()
    at.chat_input[0].set_value("How many days can I carry forward?").run()
    chat = at.session_state["chats"][1]
    assert len(chat["messages"]) == 2
    assert chat["title"] == "How many days can I carry forward?"
    assert fake_backend[0][0] == "EMP001"
    at.chat_input[0].set_value("and sick leave?").run()
    assert len(fake_backend[1][2]) == 2  # the follow-up received the first exchange as history


def test_long_questions_are_blocked(fake_backend):
    at = _logged_in()
    at.chat_input[0].set_value("x" * 501).run()
    assert any("under 500 characters" in w.value for w in at.warning)
    assert fake_backend == []


def test_new_chat_keeps_the_old_one_in_the_list():
    at = _logged_in()
    at.chat_input[0].set_value("first question").run()
    _button(at, "new_chat").click().run()
    assert at.session_state["current"] == 2
    assert at.session_state["order"] == [2, 1]
    assert any(b.key == "open_1" for b in at.sidebar.button)


def test_new_chat_on_an_empty_chat_does_not_pile_up_empty_chats():
    at = _logged_in()
    _button(at, "new_chat").click().run()
    assert len(at.session_state["chats"]) == 1


def test_clicking_a_previous_chat_switches_to_it():
    at = _logged_in()
    at.chat_input[0].set_value("first question").run()
    _button(at, "new_chat").click().run()
    at.chat_input[0].set_value("second question").run()
    _button(at, "open_1").click().run()
    assert at.session_state["current"] == 1


def test_example_question_button_sends_the_question(fake_backend):
    at = _logged_in()
    _button(at, "example_0").click().run()
    assert len(fake_backend) == 1
    assert fake_backend[0][1] == "How many leave days can I carry forward?"


def test_logout_returns_to_login():
    at = _logged_in()
    _button(at, "logout").click().run()
    assert "employee" not in at.session_state
