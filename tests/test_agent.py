from src import agent, tools


class _Router:
    def __init__(self, decision):
        self.decision = decision

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        return self.decision


def _patch_tools(monkeypatch):
    monkeypatch.setattr(
        tools, "get_leave_balance",
        lambda eid: {"name": "Sara",
                     "annual": {"total": 20, "used": 3, "remaining": 17},
                     "sick": {"total": 10, "used": 0, "remaining": 10}},
    )
    monkeypatch.setattr(tools, "escalate", lambda e, q, r: {"request_id": 1042, "hr_email": "hr@x.com"})


def test_sensitive_words_skip_the_model_and_escalate(monkeypatch):
    _patch_tools(monkeypatch)

    def no_model():
        raise AssertionError("the model must not be called for sensitive words")

    monkeypatch.setattr(agent, "get_llm", no_model)
    out = agent.run_agent("EMP001", "My manager is harassing me.")
    assert out["path"] == "escalate"
    assert "hr@x.com" in out["reply"] and "1042" in out["reply"]


def test_balance_path_uses_the_logged_in_employee(monkeypatch):
    _patch_tools(monkeypatch)
    seen = {}
    monkeypatch.setattr(tools, "get_leave_balance",
                        lambda eid: seen.setdefault("id", eid) and {
                            "name": "Sara",
                            "annual": {"total": 20, "used": 3, "remaining": 17},
                            "sick": {"total": 10, "used": 0, "remaining": 10}})
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(
        agent.Route(route="balance", leave_type="annual", detail="remaining")))
    out = agent.run_agent("EMP003", "How many annual leaves do I have left?")
    assert out["path"] == "balance"
    assert "17" in out["reply"]
    assert seen["id"] == "EMP003"


def test_policy_path_returns_answer_and_citation(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(agent.Route(route="policy")))
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: {
        "found": True, "answer": "Up to 5 days.", "reason": "",
        "citations": [{"label": "Leave Policy, Section 4.2 (Carry-forward limit)",
                       "file": "leave_policy.md", "section": "4.2"}]})
    out = agent.run_agent("EMP001", "How many days can I carry forward?")
    assert out["path"] == "policy"
    assert "Section 4.2" in out["reply"]


def test_no_source_found_escalates(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(agent.Route(route="policy")))
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: {
        "found": False, "answer": "", "citations": [], "reason": "no relevant policy text"})
    out = agent.run_agent("EMP001", "What dental insurance is offered?")
    assert out["path"] == "escalate"
    assert "could not find an answer" in out["reply"]


def test_model_marked_sensitive_escalates(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(agent.Route(route="sensitive")))
    out = agent.run_agent("EMP001", "I feel very stressed at work lately.")
    assert out["path"] == "escalate"
    assert "cannot resolve it here" in out["reply"]


def test_rule_question_is_not_treated_as_a_balance_question(monkeypatch):
    """The model wrongly says 'balance', but the question asks about a rule, so it goes to policy."""
    _patch_tools(monkeypatch)
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(
        agent.Route(route="balance", leave_type="annual", detail="remaining")))
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: {
        "found": True, "answer": "Up to 5 days.", "reason": "",
        "citations": [{"label": "Leave Policy, Section 4.2 (Carry-forward limit)",
                       "file": "leave_policy.md", "section": "4.2"}]})
    out = agent.run_agent("EMP001", "How many unused annual leave days can I carry forward?")
    assert out["path"] == "policy"


def test_greeting_gets_a_help_message_without_model_or_escalation(monkeypatch):
    def no_model():
        raise AssertionError("the model must not be called for a plain greeting")

    def no_escalation(*args):
        raise AssertionError("a greeting must not be logged as an escalation")

    monkeypatch.setattr(agent, "get_llm", no_model)
    monkeypatch.setattr(tools, "escalate", no_escalation)
    out = agent.run_agent("EMP001", "Hi")
    assert out["path"] == "other"
    assert "HR Policy Assistant" in out["reply"]


def test_model_marked_other_is_not_escalated(monkeypatch):
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(agent.Route(route="other")))
    monkeypatch.setattr(tools, "escalate", lambda *a: (_ for _ in ()).throw(AssertionError("no escalation")))
    out = agent.run_agent("EMP001", "What is the weather today?")
    assert out["path"] == "other"
