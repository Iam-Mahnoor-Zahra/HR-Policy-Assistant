"""The two-step consent flow: offer -> yes -> draft -> yes -> send. Nothing is sent without the second yes."""
from types import SimpleNamespace

import pytest

from src import agent, tools

EMPLOYEE = {"employee_id": "EMP003", "name": "Sara", "email": "sara@examplecorp.com"}
PARAGRAPH = "I would like help with how my manager treats me."


class Recorder:
    def __init__(self, info=None):
        self.calls = []
        self.info = info or {"request_id": 1042, "email_sent": True, "hr_email": "hr@x.com"}

    def __call__(self, employee_id, question, reason, subject, body):
        self.calls.append((employee_id, question, reason, subject, body))
        return self.info


class FakeModel:
    """Writes the email paragraph. The router (structured output) must NOT be used for sensitive words."""

    def __init__(self, paragraph=PARAGRAPH, fail=False):
        self.paragraph, self.fail, self.draft_calls = paragraph, fail, 0

    def invoke(self, messages):
        self.draft_calls += 1
        if self.fail:
            raise RuntimeError("model down")
        return SimpleNamespace(content=self.paragraph)

    def with_structured_output(self, schema):
        raise AssertionError("the router must not be called for sensitive words")


def _setup(monkeypatch, recorder, model=None):
    model = model or FakeModel()
    monkeypatch.setattr(tools, "get_employee", lambda eid: EMPLOYEE)
    monkeypatch.setattr(tools, "send_escalation", recorder)
    monkeypatch.setattr(agent, "get_llm", lambda: model)
    return model


MESSAGE = "my manager is misbehaving with me"


def _offer():
    return agent.run_agent("EMP003", MESSAGE)


def _say(text, pending):
    return agent.run_agent("EMP003", text, pending=pending)


def test_full_flow_sends_only_after_the_second_yes(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec)

    step1 = _offer()
    assert step1["path"] == "escalate_offer" and rec.calls == []

    step2 = _say("yes", step1["pending"])
    assert step2["path"] == "escalate_draft"
    assert "**Subject:**" in step2["reply"] and "Dear HR team," in step2["reply"]
    assert PARAGRAPH in step2["reply"] and MESSAGE in step2["reply"]
    assert "Shall I send it?" in step2["reply"]
    assert rec.calls == []  # still nothing sent

    step3 = _say("yes", step2["pending"])
    assert step3["path"] == "escalate_sent"
    assert "ID 1042" in step3["reply"] and "hr@x.com" in step3["reply"]
    assert step3["pending"] is None
    assert len(rec.calls) == 1
    assert rec.calls[0][0] == "EMP003" and rec.calls[0][2] == "sensitive topic"
    assert rec.calls[0][1] == MESSAGE  # the employee's own words are saved


@pytest.mark.parametrize("text", ["yes", "Yes!", "yes plz", "yes please", "yeah sure", "ok", "okay",
                                  "please send it", "go ahead", "send the email", "yep", "do it"])
def test_friendly_yes_answers_are_understood(monkeypatch, text):
    _setup(monkeypatch, Recorder())
    assert _say(text, _offer()["pending"])["path"] == "escalate_draft"


@pytest.mark.parametrize("text", ["no", "No thanks", "nope", "don't send it", "do not send", "cancel", "no i don't want to"])
def test_friendly_no_answers_are_understood(monkeypatch, text):
    rec = Recorder()
    _setup(monkeypatch, rec)
    assert _say(text, _offer()["pending"])["path"] == "escalate_declined"
    assert rec.calls == []


@pytest.mark.parametrize("text", ["yes but what about sick leave?", "ok thanks", "what is 2+2?", "maybe later",
                                  "yes I think my manager also shouted at me yesterday"])
def test_unclear_answers_are_not_a_yes(monkeypatch, text):
    rec = Recorder()
    _setup(monkeypatch, rec)
    assert agent._yes_no(text) is None


def test_no_to_the_draft_sends_nothing(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec)
    draft = _say("yes", _offer()["pending"])
    out = _say("no thanks", draft["pending"])
    assert out["path"] == "escalate_declined" and rec.calls == []


def test_after_a_no_the_employee_can_ask_to_send_the_email(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec)
    declined = _say("no", _offer()["pending"])
    assert "send the email" in declined["reply"]
    revived = _say("can you send the email", declined["pending"])
    assert revived["path"] == "escalate_draft" and MESSAGE in revived["reply"]
    assert rec.calls == []  # still needs the final yes
    sent = _say("yes plz", revived["pending"])
    assert sent["path"] == "escalate_sent" and len(rec.calls) == 1


def test_after_a_no_another_message_is_handled_normally(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec)
    declined = _say("no", _offer()["pending"])
    monkeypatch.setattr(agent, "get_llm", lambda: SimpleNamespace(
        with_structured_output=lambda s: SimpleNamespace(invoke=lambda m: agent.Route(route="other"))))
    out = _say("What is the weather today?", declined["pending"])
    assert out["path"] == "other" and out["pending"] is None and rec.calls == []


def test_another_message_drops_the_offer_and_sends_nothing(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec)
    pending = _offer()["pending"]
    monkeypatch.setattr(agent, "get_llm", lambda: SimpleNamespace(
        with_structured_output=lambda s: SimpleNamespace(invoke=lambda m: agent.Route(route="other"))))
    out = _say("What is the weather today?", pending)
    assert out["path"] == "other" and out["pending"] is None and rec.calls == []


def test_the_employees_own_words_are_quoted_even_if_the_question_was_rewritten(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec)
    # the standalone (rewritten) question differs from what the employee typed
    pending = {"type": "escalate_offer", "reason": "sensitive topic",
               "question": "Can you please help me address the issue of my manager misbehaving with me?",
               "original": MESSAGE}
    draft = _say("yes", pending)
    assert f'"{MESSAGE}"' in draft["reply"]
    assert "Can you please help me address" not in draft["reply"]


def test_if_the_model_cannot_write_the_paragraph_a_plain_one_is_used(monkeypatch):
    rec = Recorder()
    _setup(monkeypatch, rec, model=FakeModel(fail=True))
    draft = _say("yes", _offer()["pending"])
    assert draft["path"] == "escalate_draft"
    assert "raise a concern" in draft["reply"]


def test_email_failure_is_reported_honestly(monkeypatch):
    rec = Recorder({"request_id": 1042, "email_sent": False, "hr_email": "hr@x.com"})
    _setup(monkeypatch, rec)
    draft = _say("yes", _offer()["pending"])
    out = _say("yes", draft["pending"])
    assert "saved your request (ID 1042)" in out["reply"] and "could not send the email" in out["reply"]


def test_nothing_saved_and_nothing_sent_is_reported_honestly(monkeypatch):
    rec = Recorder({"request_id": None, "email_sent": False, "hr_email": "hr@x.com"})
    _setup(monkeypatch, rec)
    draft = _say("yes", _offer()["pending"])
    out = _say("yes", draft["pending"])
    assert "could not send the email or save your request" in out["reply"]
    assert "hr@x.com" in out["reply"]
