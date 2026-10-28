from types import SimpleNamespace

from src import agent


class _Model:
    """Fake model: plain invoke() is the question rewriter, structured output is the router."""

    def __init__(self, rewritten=None, decision=None):
        self.rewritten = rewritten
        self.decision = decision
        self.rewrite_calls = 0

    def invoke(self, messages):
        self.rewrite_calls += 1
        return SimpleNamespace(content=self.rewritten)

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda messages: self.decision)


HISTORY = [
    {"role": "user", "content": "How many annual leave days do employees get each year?"},
    {"role": "assistant", "content": "Employees get 20 annual leave days per year."},
]


def _found(q):
    return {"found": True, "answer": "10 days.", "reason": "",
            "citations": [{"label": "Leave Policy, Section 3.1 (Entitlement)",
                           "file": "leave_policy.md", "section": "3.1"}]}


def test_follow_up_is_rewritten_before_search(monkeypatch):
    model = _Model(rewritten="How many sick leave days are allowed per year?",
                   decision=agent.Route(route="policy"))
    seen = {}
    monkeypatch.setattr(agent, "get_llm", lambda: model)
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: seen.setdefault("q", q) and _found(q))
    out = agent.run_agent("EMP001", "and what about sick leave?", history=HISTORY)
    assert out["path"] == "policy"
    assert seen["q"] == "How many sick leave days are allowed per year?"


def test_no_history_means_no_rewrite_call(monkeypatch):
    model = _Model(rewritten="should not be used", decision=agent.Route(route="policy"))
    monkeypatch.setattr(agent, "get_llm", lambda: model)
    monkeypatch.setattr(agent, "answer_policy_question", _found)
    agent.run_agent("EMP001", "and what about sick leave?")
    assert model.rewrite_calls == 0


def test_long_questions_greetings_and_sensitive_messages_are_not_rewritten(monkeypatch):
    model = _Model(rewritten="REWRITTEN", decision=agent.Route(route="policy"))
    monkeypatch.setattr(agent, "get_llm", lambda: model)
    long_q = "How many annual leave days do employees get each calendar year in total?"
    assert agent._standalone_question(long_q, HISTORY) == long_q
    assert agent._standalone_question("Hi", HISTORY) == "Hi"
    assert agent._standalone_question("He is harassing me", HISTORY) == "He is harassing me"
    assert model.rewrite_calls == 0


def test_if_the_rewrite_fails_the_original_question_is_used(monkeypatch):
    class Broken(_Model):
        def invoke(self, messages):
            raise RuntimeError("network")

    monkeypatch.setattr(agent, "get_llm", lambda: Broken())
    assert agent._standalone_question("and sick leave?", HISTORY) == "and sick leave?"
