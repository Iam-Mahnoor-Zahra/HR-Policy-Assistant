"""Saved chat history: chats survive logout, per employee."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    from src import agent, db

    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("SKIP_KB_SETUP", "1")
    people = {"EMP001": "Ayesha", "EMP003": "Sara"}
    monkeypatch.setattr(db, "fetch_employee",
                        lambda eid: {"employee_id": eid, "name": people[eid]} if eid in people else None)
    monkeypatch.setattr(
        agent, "run_agent",
        lambda employee_id, question, history=None, pending=None:
        {"pending": {"type": "leave_confirm"} if question == "leave" else None,
         "reply": f"answer to {question}", "path": "policy", "request_id": None, "citations": []},
    )


def _login(employee_id="EMP001"):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].set_value(employee_id)
    at.text_input[1].set_value("secret")
    at.button[0].click().run()
    return at


def _button(at, key):
    return next(b for b in list(at.sidebar.button) + list(at.button) if b.key == key)


def test_a_question_is_saved_and_updated_in_the_same_row(chat_store):
    at = _login()
    at.chat_input[0].set_value("first question").run()
    assert len(chat_store.rows) == 1
    row = chat_store.rows[0]
    assert row["employee_id"] == "EMP001" and row["title"] == "first question"
    assert [m["content"] for m in row["messages"]] == ["first question", "answer to first question"]
    at.chat_input[0].set_value("second question").run()
    assert len(chat_store.rows) == 1 and len(chat_store.rows[0]["messages"]) == 4


def test_the_chat_is_back_after_logout_and_login(chat_store):
    at = _login()
    at.chat_input[0].set_value("how many days carry forward").run()
    _button(at, "logout").click().run()
    at = _login()
    assert len(at.session_state["chats"]) == 2
    current = at.session_state["chats"][at.session_state["current"]]
    assert current["messages"] == []  # a fresh empty chat is ready
    assert any(b.key == "open_1" for b in at.sidebar.button)  # the old one is in the list
    _button(at, "open_1").click().run()
    old = at.session_state["chats"][at.session_state["current"]]
    assert old["title"] == "how many days carry forward" and len(old["messages"]) == 2


def test_continuing_an_old_chat_updates_it_instead_of_making_a_new_row(chat_store):
    at = _login()
    at.chat_input[0].set_value("question one").run()
    _button(at, "logout").click().run()
    at = _login()
    _button(at, "open_1").click().run()
    at.chat_input[0].set_value("question two").run()
    assert len(chat_store.rows) == 1 and len(chat_store.rows[0]["messages"]) == 4


def test_newest_chat_is_first_in_the_list(chat_store):
    chat_store.insert("EMP001", "older", [{"role": "user", "content": "a"}])
    chat_store.insert("EMP001", "newer", [{"role": "user", "content": "b"}])
    at = _login()
    titles = [at.session_state["chats"][i]["title"] for i in at.session_state["order"]]
    assert titles == ["New chat", "newer", "older"]


def test_employees_only_see_their_own_chats(chat_store):
    chat_store.insert("EMP001", "Ayesha's private chat", [{"role": "user", "content": "x"}])
    at = _login("EMP003")
    titles = [c["title"] for c in at.session_state["chats"].values()]
    assert titles == ["New chat"]


def test_an_open_yes_no_step_is_not_restored(chat_store):
    at = _login()
    at.chat_input[0].set_value("leave").run()  # the agent leaves a pending step
    assert at.session_state["chats"][1]["pending"] == {"type": "leave_confirm"}
    _button(at, "logout").click().run()
    at = _login()
    old = next(c for c in at.session_state["chats"].values() if c["title"] == "leave")
    assert old["pending"] is None


def test_a_database_failure_does_not_break_the_chat(chat_store):
    chat_store.fail = True
    at = _login()  # loading fails: the app still opens with one empty chat
    assert len(at.session_state["chats"]) == 1
    at.chat_input[0].set_value("hello there").run()  # saving fails: the answer still appears
    assert not at.exception
    assert len(at.session_state["chats"][1]["messages"]) == 2
