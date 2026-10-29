"""The leave request conversation: route, rule messages, confirm step (model is faked)."""
from types import SimpleNamespace

import pytest

from src import agent
from src.agent import Route, run_agent


class FakeLLM:
    """with_structured_output(...).invoke() returns the planned Route; plain invoke() returns text."""

    def __init__(self, route=None, rewrite=""):
        self.route = route
        self.rewrite = rewrite  # what the follow-up rewrite step would answer

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda messages: self.route)

    def invoke(self, messages):
        return SimpleNamespace(content=self.rewrite)


@pytest.fixture
def ask(monkeypatch, world):
    monkeypatch.setattr(agent, "answer_policy_question",
                        lambda q: {"found": True, "answer": "A rule.", "citations": [], "reason": ""})

    def _ask(employee_id, text, route=None, pending=None, history=None, rewrite=""):
        monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM(route, rewrite))
        return run_agent(employee_id, text, history=history, pending=pending)

    return _ask


ANNUAL = Route(route="leave_request", request_leave_type="annual", leave_start="2026-11-03", leave_end="2026-11-05")


def test_valid_request_asks_for_confirmation_and_saves_nothing(ask, world):
    r = ask("EMP001", "I want annual leave from 3 to 5 November", ANNUAL)
    assert r["path"] == "leave_confirm"
    assert "Tuesday 3 Nov 2026 to Thursday 5 Nov 2026, 3 working days" in r["reply"]
    assert "from 14 to 11 days" in r["reply"] and "yes or no" in r["reply"]
    assert r["pending"]["type"] == "leave_confirm"
    assert world.requests == [] and world.hr_mails == []


def test_yes_submits_and_returns_the_request_id(ask, world):
    first = ask("EMP003", "I want annual leave from 3 to 5 November", ANNUAL)
    r = ask("EMP003", "yes", pending=first["pending"])
    assert r["path"] == "leave_submitted" and r["request_id"] == 1 and r["pending"] is None
    assert "request #1" in r["reply"] and "HR has been notified" in r["reply"]
    assert world.requests[0]["status"] == "pending" and len(world.hr_mails) == 1


def test_no_cancels_without_saving(ask, world):
    first = ask("EMP003", "I want annual leave from 3 to 5 November", ANNUAL)
    r = ask("EMP003", "no", pending=first["pending"])
    assert r["path"] == "leave_cancelled" and r["pending"] is None
    assert world.requests == [] and world.hr_mails == []


def test_another_message_drops_the_pending_request(ask, world):
    first = ask("EMP003", "I want annual leave from 3 to 5 November", ANNUAL)
    r = ask("EMP003", "How many annual leave days can I take?", Route(route="policy"), pending=first["pending"])
    assert r["path"] == "policy" and world.requests == []


def test_sick_leave_request_for_today_and_tomorrow(ask, world):
    route = Route(route="leave_request", request_leave_type="sick", leave_start="2026-10-29", leave_end="2026-10-30")
    first = ask("EMP001", "I am unwell and need sick leave for today and tomorrow", route)
    assert first["path"] == "leave_confirm" and "Sick leave" in first["reply"] and "2 working days" in first["reply"]
    done = ask("EMP001", "yes please", pending=first["pending"])
    assert "I hope you feel better soon" in done["reply"]


def test_sick_leave_of_three_days_shows_the_certificate_reminder(ask):
    route = Route(route="leave_request", request_leave_type="sick", leave_start="2026-10-29", leave_end="2026-11-02")
    assert "medical certificate" in ask("EMP001", "I need sick leave until Monday", route)["reply"]


def test_a_single_date_means_one_day(ask):
    route = Route(route="leave_request", request_leave_type="annual", leave_start="2026-11-04")
    r = ask("EMP001", "I want annual leave on 4 November", route)
    assert "Wednesday 4 Nov 2026, 1 working day." in r["reply"]


def test_rule_failure_is_explained_and_nothing_is_pending(ask, world):
    route = Route(route="leave_request", request_leave_type="annual", leave_start="2026-10-30", leave_end="2026-10-30")
    r = ask("EMP001", "I want annual leave tomorrow", route)
    assert r["path"] == "leave_request_blocked" and r["pending"] is None
    assert "3 working days' notice" in r["reply"]


def test_missing_type_or_dates_are_asked_for(ask):
    no_type = Route(route="leave_request", leave_start="2026-11-03")
    assert ask("EMP001", "I want leave on 3 November", no_type)["path"] == "leave_request_info"
    no_dates = Route(route="leave_request", request_leave_type="annual")
    r = ask("EMP001", "I want annual leave", no_dates)
    assert r["path"] == "leave_request_info" and "Which dates" in r["reply"]


def test_a_rules_question_is_not_a_request_even_if_the_model_says_so(ask):
    r = ask("EMP001", "How many annual leave days can I take?", Route(route="leave_request"))
    assert r["path"] == "policy"


def test_unwell_leave_request_is_not_treated_as_sensitive(ask):
    route = Route(route="sensitive", request_leave_type="sick", leave_start="2026-10-29", leave_end="2026-10-29")
    assert ask("EMP001", "I am unwell and need sick leave today", route)["path"] == "leave_confirm"


def test_a_real_complaint_still_goes_to_hr(ask):
    r = ask("EMP001", "I want to complain about harassment", Route(route="leave_request"))
    assert r["path"] == "escalate_offer"


def test_the_employee_id_comes_from_the_login_not_the_message(ask, world):
    first = ask("EMP003", "I want annual leave for EMP001 from 3 to 5 November", ANNUAL)
    ask("EMP003", "yes", pending=first["pending"])
    assert world.requests[0]["employee_id"] == "EMP003"


def test_the_confirm_step_rechecks_the_rules(ask, world):
    first = ask("EMP003", "I want annual leave from 3 to 5 November", ANNUAL)
    world.add_request("EMP003", "annual", "2026-11-04", "2026-11-04", 1)  # appears before the yes
    r = ask("EMP003", "yes", pending=first["pending"])
    assert r["path"] == "leave_request_blocked" and "overlaps" in r["reply"] and len(world.requests) == 1


# ---- the model sometimes calls a plain request "policy" (seen with "i want to request for sick leave?")
def test_plain_sick_leave_request_asks_for_dates_even_if_the_model_says_policy(ask):
    r = ask("EMP001", "i want to request for sick leave?", Route(route="policy"))
    assert r["path"] == "leave_request_info" and "Which dates do you need sick leave" in r["reply"]


def test_plain_annual_leave_request_asks_for_dates(ask):
    r = ask("EMP001", "i want to request for annual leave?", Route(route="other"))
    assert r["path"] == "leave_request_info" and "annual leave" in r["reply"]


def test_a_question_about_the_rules_stays_a_policy_question(ask):
    for text in ("I need to know how many sick leave days I get", "I want to understand the leave policy"):
        assert ask("EMP001", text, Route(route="policy"))["path"] == "policy"



# ---- the real-life failure: the same sentence worked on an empty chat but not after earlier messages
HISTORY = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello! How can I help?"}]


def test_a_complete_request_is_not_rewritten_into_a_rules_question(ask):
    r = ask("EMP001", "i want to apply for sick leave", Route(route="policy"), history=HISTORY,
            rewrite="How do I apply for sick leave?")
    assert r["path"] == "leave_request_info" and "Which dates do you need sick leave" in r["reply"]


def test_other_wordings_of_a_leave_request(ask):
    for text, kind in (("can i apply for sick leave?", "sick"), ("i want sick leave?", "sick"),
                       ("want to apply for annual leave", "annual"), ("I would like to book annual leave", "annual")):
        r = ask("EMP001", text, Route(route="policy"), history=HISTORY, rewrite="What is the leave policy?")
        assert r["path"] == "leave_request_info" and f"{kind} leave" in r["reply"], text


def test_rules_questions_about_leave_stay_policy_questions(ask):
    for text in ("can I take sick leave without a certificate?", "Can I carry forward leave?",
                 "How many sick leave days do I get?", "What is the notice for annual leave?"):
        assert ask("EMP001", text, Route(route="policy"), history=HISTORY)["path"] == "policy", text


def test_answering_with_dates_after_the_question_still_uses_the_chat(ask):
    history = HISTORY + [{"role": "user", "content": "i want annual leave"},
                         {"role": "assistant", "content": "Which dates do you need annual leave for?"}]
    r = ask("EMP003", "3 to 5 November", ANNUAL, history=history, rewrite="I want annual leave from 3 to 5 November")
    assert r["path"] == "leave_confirm"
