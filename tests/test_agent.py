from src import agent, tools


class _Router:
    def __init__(self, decision):
        self.decision = decision

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        return self.decision


BALANCE = {"name": "Sara",
           "annual": {"total": 20, "used": 3, "remaining": 17},
           "sick": {"total": 10, "used": 0, "remaining": 10}}


def _no_send(*args, **kwargs):
    raise AssertionError("nothing may be saved or emailed before the employee confirms")


def _patch_tools(monkeypatch):
    monkeypatch.setattr(tools, "get_leave_balance", lambda eid: BALANCE)
    monkeypatch.setattr(tools, "send_escalation", _no_send)


def _router(monkeypatch, **decision):
    monkeypatch.setattr(agent, "get_llm", lambda: _Router(agent.Route(**decision)))


def _policy_found(monkeypatch):
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: {
        "found": True, "answer": "Up to 5 days.", "reason": "",
        "citations": [{"label": "Leave Policy, Section 4.2 (Carry-forward limit)",
                       "file": "leave_policy.md", "section": "4.2"}]})


def _policy_missing(monkeypatch):
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: {
        "found": False, "answer": "", "citations": [], "reason": "no relevant policy text"})


# ------------------------------------------------------------ routing: existing paths
def test_sensitive_words_skip_the_model_and_only_offer_to_email_hr(monkeypatch):
    _patch_tools(monkeypatch)

    def no_model():
        raise AssertionError("the model must not be called for sensitive words")

    monkeypatch.setattr(agent, "get_llm", no_model)
    out = agent.run_agent("EMP001", "My manager is harassing me.")
    assert out["path"] == "escalate_offer"
    assert "Would you like me to email HR" in out["reply"]
    assert out["pending"]["type"] == "escalate_offer"


def test_balance_path_uses_the_logged_in_employee(monkeypatch):
    _patch_tools(monkeypatch)
    seen = {}
    monkeypatch.setattr(tools, "get_leave_balance", lambda eid: seen.setdefault("id", eid) and BALANCE)
    _router(monkeypatch, route="balance", leave_type="annual", detail="remaining")
    out = agent.run_agent("EMP003", "How many annual leaves do I have left?")
    assert out["path"] == "balance" and "17" in out["reply"]
    assert seen["id"] == "EMP003"


def test_policy_path_returns_answer_and_citation(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="policy")
    _policy_found(monkeypatch)
    out = agent.run_agent("EMP001", "How many days can I carry forward?")
    assert out["path"] == "policy" and "Section 4.2" in out["reply"]
    assert out["pending"] is None


def test_no_source_found_offers_to_email_hr(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="policy")
    _policy_missing(monkeypatch)
    out = agent.run_agent("EMP001", "What dental insurance is offered?")
    assert out["path"] == "escalate_offer"
    assert "could not find an answer" in out["reply"]
    assert out["pending"]["reason"] == "no source found"


def test_model_marked_sensitive_offers_to_email_hr(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="sensitive")
    out = agent.run_agent("EMP001", "I feel very stressed at work lately.")
    assert out["path"] == "escalate_offer"
    assert "cannot resolve it here" in out["reply"]


def test_rule_question_is_not_treated_as_a_balance_question(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="balance", leave_type="annual", detail="remaining")
    _policy_found(monkeypatch)
    out = agent.run_agent("EMP001", "How many unused annual leave days can I carry forward?")
    assert out["path"] == "policy"


def test_greeting_gets_a_help_message_without_model(monkeypatch):
    _patch_tools(monkeypatch)

    def no_model():
        raise AssertionError("the model must not be called for a plain greeting")

    monkeypatch.setattr(agent, "get_llm", no_model)
    out = agent.run_agent("EMP001", "Hi")
    assert out["path"] == "other" and "HR Policy Assistant" in out["reply"]


def test_model_marked_other_is_not_escalated(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="other")
    _policy_missing(monkeypatch)
    out = agent.run_agent("EMP001", "What is the weather today?")
    assert out["path"] == "other" and out["pending"] is None


def test_salary_question_is_not_small_talk(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="other")
    _policy_missing(monkeypatch)
    out = agent.run_agent("EMP001", "Can you tell me what my current salary is?")
    assert out["path"] == "escalate_offer"


# ------------------------------------------------------------- new route: status
LEAVE_ROW = {"id": 7, "leave_type": "annual", "start_date": "2026-11-03", "end_date": "2026-11-05",
             "working_days": 3, "status": "pending"}
HR_ROW = {"id": 12, "status": "emailed", "created_at": "2026-10-26T10:15:00+00:00"}


def test_status_route_shows_the_employees_requests(monkeypatch):
    _patch_tools(monkeypatch)
    seen = {}
    monkeypatch.setattr(tools, "get_request_status", lambda eid, rid=None, kind="any": seen.update(
        eid=eid, rid=rid, kind=kind) or {"leave": [LEAVE_ROW], "hr": [HR_ROW]})
    _router(monkeypatch, route="status", request_id=None, request_kind="any")
    out = agent.run_agent("EMP003", "What is the status of my requests?")
    assert out["path"] == "status"
    assert "Leave request #7" in out["reply"] and "3 Nov 2026" in out["reply"] and "pending" in out["reply"]
    assert "HR request #12" in out["reply"] and "emailed to HR" in out["reply"]
    assert seen["eid"] == "EMP003"


def test_status_for_a_missing_request_says_so(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(tools, "get_request_status", lambda eid, rid=None, kind="any": {"leave": [], "hr": []})
    _router(monkeypatch, route="status", request_id=99, request_kind="leave")
    out = agent.run_agent("EMP003", "What is the status of my leave request 99?")
    assert "could not find request #99" in out["reply"]


def test_status_route_needs_status_words_otherwise_policy(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="status")
    _policy_found(monkeypatch)
    out = agent.run_agent("EMP001", "How many days can I carry forward?")
    assert out["path"] == "policy"


# ------------------------------------------------------------ new route: holiday
def test_holiday_on_a_specific_date(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(tools, "get_holiday", lambda d: {"name": "Company Foundation Day"})
    _router(monkeypatch, route="holiday", holiday_date="2026-11-09")
    out = agent.run_agent("EMP001", "Is 9 November a holiday?")
    assert out["path"] == "holiday"
    assert "Yes, 9 Nov 2026 (Monday) is a company holiday: Company Foundation Day." in out["reply"]


def test_a_normal_working_day_is_not_a_holiday(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(tools, "get_holiday", lambda d: None)
    _router(monkeypatch, route="holiday", holiday_date="2026-11-10")
    out = agent.run_agent("EMP001", "Is 10 November a holiday?")
    assert "not a company holiday" in out["reply"]


def test_a_weekend_is_called_a_weekend(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(tools, "get_holiday", lambda d: None)
    _router(monkeypatch, route="holiday", holiday_date="2026-11-07")  # a Saturday
    out = agent.run_agent("EMP001", "Is 7 November a holiday?")
    assert "weekend" in out["reply"]


def test_upcoming_holidays_are_listed(monkeypatch):
    _patch_tools(monkeypatch)
    monkeypatch.setattr(tools, "list_holidays", lambda d, limit=5: [
        {"holiday_date": "2026-11-09", "name": "Company Foundation Day"},
        {"holiday_date": "2026-12-25", "name": "Year-End Holiday"}])
    _router(monkeypatch, route="holiday", holiday_date=None)
    out = agent.run_agent("EMP001", "What are the next company holidays?")
    assert "9 Nov 2026 (Monday): Company Foundation Day" in out["reply"]
    assert "25 Dec 2026 (Friday): Year-End Holiday" in out["reply"]


def test_holiday_route_needs_holiday_words_otherwise_policy(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="holiday")
    _policy_found(monkeypatch)
    out = agent.run_agent("EMP001", "How many days can I carry forward?")
    assert out["path"] == "policy"


# ------------------------------------- "other" lets the policy search decide (no keywords)
def test_other_is_answered_from_the_policies_when_a_section_matches(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="other")
    monkeypatch.setattr(agent, "answer_policy_question", lambda q: {
        "found": True, "answer": "Treat everyone with respect and professionalism.", "reason": "",
        "citations": [{"label": "Code of Conduct, Section 1.1 (Expected behaviour)",
                       "file": "code_of_conduct.md", "section": "1.1"}]})
    out = agent.run_agent("EMP001", "what should be the employee behaviour in a company")
    assert out["path"] == "policy" and "Section 1.1" in out["reply"]
    assert out["citations"] and out["pending"] is None


def test_other_with_no_matching_section_shows_the_help_text(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="other")
    _policy_missing(monkeypatch)
    out = agent.run_agent("EMP001", "What is the weather today?")
    assert out["path"] == "other" and "HR Policy Assistant" in out["reply"]
    assert out["pending"] is None


def test_what_can_you_do_never_searches_the_policies(monkeypatch):
    _patch_tools(monkeypatch)
    _router(monkeypatch, route="other")

    def no_search(q):
        raise AssertionError("the policy search must not run for questions about the assistant")

    monkeypatch.setattr(agent, "answer_policy_question", no_search)
    out = agent.run_agent("EMP001", "What can you do?")
    assert out["path"] == "other" and "HR Policy Assistant" in out["reply"]


def test_greeting_never_searches_the_policies(monkeypatch):
    _patch_tools(monkeypatch)

    def no_model():
        raise AssertionError("no model for a greeting")

    def no_search(q):
        raise AssertionError("no search for a greeting")

    monkeypatch.setattr(agent, "get_llm", no_model)
    monkeypatch.setattr(agent, "answer_policy_question", no_search)
    assert agent.run_agent("EMP001", "Thanks")["path"] == "other"
