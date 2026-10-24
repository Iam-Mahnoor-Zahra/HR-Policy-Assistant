"""The agent: a LangGraph workflow that decides what to do with each employee question.

    question -> classify -> sensitive -> escalate (log + HR email)
                         -> other     -> short help message (greetings, thanks, off-topic)
                         -> balance   -> leave balance tool
                         -> policy    -> policy search -> answer with citation
                                                       -> no source found -> escalate

Try it from the project root:
    python -m src.agent --employee EMP003 "How many annual leave days do I have left?"
    python -m src.agent "How many unused annual leave days can I carry forward?"
    python -m src.agent "My manager is harassing me."
Run without a question to chat in the terminal.
"""
import re
import sys
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from src import tools
from src.llm import get_llm
from src.qa import answer_policy_question

# Safety net: these words always go to HR, without asking the model.
SENSITIVE_WORDS = (
    "harass", "bully", "bullied", "discriminat", "abuse", "assault",
    "threat", "retaliat", "unfair", "complaint", "grievance",
)

ROUTER_PROMPT = """Classify the employee's message into one route.

sensitive: complaints, harassment, bullying, discrimination, unfair treatment, conflicts with a manager or colleague, legal, medical or mental health matters, or a request to talk to a person.
balance: ONLY when the employee asks for their OWN current leave numbers (days left, used or total).
policy: any question about company rules, limits, eligibility or procedures, or any other HR topic (pay, benefits, insurance, contracts), even if it mentions "I" or leave days. A later step checks whether the documents cover it.
other: ONLY greetings, thanks, questions about what the assistant can do, or topics clearly unrelated to work.

Examples:
- "How many annual leave days do I have left?" -> balance (annual, remaining)
- "What is my sick leave balance?" -> balance (sick, remaining)
- "How many sick days have I used?" -> balance (sick, used)
- "How many unused annual leave days can I carry forward?" -> policy (it asks about a rule)
- "How many annual leave days do employees get each year?" -> policy (it asks about a rule)
- "How long do I have to submit an expense claim?" -> policy
- "My manager is treating me badly" -> sensitive
- "What is my current salary?" -> policy (an HR topic, the document search will decide)
- "Hi" -> other
- "What can you do?" -> other
- "What is the weather today?" -> other

If the route is balance, also set leave_type (annual, sick or both) and detail (remaining, used or total)."""


# Second safety net for the router: a balance question must refer to the employee's own
# numbers AND mention leave. Otherwise it is treated as a policy question.
OWN_HINTS = re.compile(r"\b(my|i have|have i|i've|left|remaining|balance|taken)\b", re.I)
LEAVE_HINTS = re.compile(r"\b(leave|leaves|annual|sick|vacation|holiday|holidays)\b", re.I)


# HR topics must never end up in the small-talk route.
HR_TOPICS = re.compile(
    r"\b(salary|salaries|pay|payslip|bonus|insurance|benefit|benefits|contract|resign|resignation|"
    r"terminate|termination|promotion|appraisal|increment|raise)\b",
    re.I,
)


def _asks_own_balance(question: str) -> bool:
    return bool(OWN_HINTS.search(question) and LEAVE_HINTS.search(question))


# Plain greetings and thanks are answered without calling the model.
GREETING = re.compile(r"(hi+|hello|hey|salam|assalam[\w\s]*|thanks|thank you|thx|ok|okay)[\s!.?]*", re.I)

HELP_TEXT = (
    "Hi, I'm the HR Policy Assistant. I can answer questions about company HR policies, "
    "check your leave balance, and point you to HR for sensitive matters. "
    "What would you like to know?"
)


REWRITE_PROMPT = """Rewrite the employee's latest message as one complete, standalone question. Use the chat history only to fill in missing details, for example what "that" or "and sick leave?" refers to.
Do not answer it. If the message already makes sense on its own, return it unchanged. Output only the question."""


class Route(BaseModel):
    route: Literal["sensitive", "balance", "policy", "other"]
    leave_type: Literal["annual", "sick", "both"] = "annual"
    detail: Literal["remaining", "used", "total"] = "remaining"


class AgentState(TypedDict, total=False):
    employee_id: str
    question: str
    route: str
    leave_type: str
    detail: str
    escalation_reason: str
    reply: str
    path: str
    citations: list
    request_id: int


def _has_sensitive_word(question: str) -> bool:
    return any(word in question.lower() for word in SENSITIVE_WORDS)


def _standalone_question(question: str, history: list | None) -> str:
    """Turn a short follow-up ("and sick leave?") into a full question using the recent chat.

    Only runs when there is chat history and the message is short, so most questions
    cost nothing extra. Greetings and sensitive messages are never rewritten.
    """
    if not history:
        return question
    if GREETING.fullmatch(question.strip()) or _has_sensitive_word(question):
        return question
    if len(question.split()) > 8:
        return question
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
    try:
        reply = get_llm().invoke(
            [("system", REWRITE_PROMPT),
             ("human", f"Chat history:\n{transcript}\n\nLatest message: {question}")]
        )
        text = (reply.content or "").strip()
    except Exception:
        return question
    return text if text and len(text) <= 300 else question


def classify(state: AgentState) -> dict:
    if GREETING.fullmatch(state["question"].strip()):
        return {"route": "other"}
    if any(word in state["question"].lower() for word in SENSITIVE_WORDS):
        return {"route": "sensitive", "escalation_reason": "sensitive topic"}
    decision = get_llm().with_structured_output(Route).invoke(
        [("system", ROUTER_PROMPT), ("human", state["question"])]
    )
    if decision.route == "sensitive":
        return {"route": "sensitive", "escalation_reason": "sensitive topic"}
    if decision.route == "other":
        if HR_TOPICS.search(state["question"]):
            return {"route": "policy"}
        return {"route": "other"}
    if decision.route == "balance" and not _asks_own_balance(state["question"]):
        return {"route": "policy"}
    return {"route": decision.route, "leave_type": decision.leave_type, "detail": decision.detail}


def policy_node(state: AgentState) -> dict:
    result = answer_policy_question(state["question"])
    if not result["found"]:
        return {"escalation_reason": "no source found"}
    lines = [result["answer"]] + [f"Source: {c['label']}" for c in result["citations"]]
    return {"reply": "\n".join(lines), "citations": result["citations"], "path": "policy"}


def _format_balance(data: dict, leave_type: str, detail: str) -> str:
    kinds = ["annual", "sick"] if leave_type == "both" else [leave_type]
    parts = []
    for kind in kinds:
        b = data[kind]
        if detail == "used":
            parts.append(f"You have used {b['used']} of your {b['total']} {kind} leave days.")
        elif detail == "total":
            parts.append(f"Your {kind} leave allowance is {b['total']} days per year.")
        else:
            parts.append(
                f"You have {b['remaining']} {kind} leave days remaining "
                f"({b['used']} used out of {b['total']})."
            )
    return " ".join(parts)


def balance_node(state: AgentState) -> dict:
    data = tools.get_leave_balance(state["employee_id"])  # the ID comes from the login, not the model
    if data is None:
        reply = "I could not find your employee record, so I cannot check your leave balance."
    else:
        reply = _format_balance(data, state.get("leave_type", "annual"), state.get("detail", "remaining"))
        reply += "\nSource: Employee records"
    return {"reply": reply, "path": "balance"}


def other_node(state: AgentState) -> dict:
    return {"reply": HELP_TEXT, "path": "other"}


def escalate_node(state: AgentState) -> dict:
    reason = state.get("escalation_reason", "sensitive topic")
    info = tools.escalate(state["employee_id"], state["question"], reason)
    if reason == "sensitive topic":
        opening = "This needs attention from HR, and I cannot resolve it here."
    else:
        opening = "I could not find an answer to this in the HR policies."
    if info["request_id"] is not None:
        follow = (
            f"Please email HR at {info['hr_email']} and include your request ID "
            f"({info['request_id']}). I have also logged your request so there is a record of it."
        )
    else:
        follow = (
            f"Please email HR at {info['hr_email']} and describe your question. "
            "I could not log your request, so the email is the only record."
        )
    return {"reply": f"{opening} {follow}", "path": "escalate", "request_id": info["request_id"]}


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", classify)
    g.add_node("policy", policy_node)
    g.add_node("balance", balance_node)
    g.add_node("escalate", escalate_node)
    g.add_node("other", other_node)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        lambda s: s["route"],
        {"sensitive": "escalate", "balance": "balance", "policy": "policy", "other": "other"},
    )
    g.add_conditional_edges(
        "policy",
        lambda s: "done" if s.get("path") == "policy" else "escalate",
        {"done": END, "escalate": "escalate"},
    )
    g.add_edge("balance", END)
    g.add_edge("other", END)
    g.add_edge("escalate", END)
    return g.compile()


graph = _build_graph()


def run_agent(employee_id: str, question: str, history: list | None = None) -> dict:
    """Run one question. Returns {"reply", "path", "citations", "request_id"}.

    history: earlier messages of this chat as [{"role": "user" or "assistant", "content": "..."}].
    """
    standalone = _standalone_question(question, history)
    out = graph.invoke({"employee_id": employee_id, "question": standalone})
    return {
        "reply": out["reply"],
        "path": out["path"],
        "citations": out.get("citations", []),
        "request_id": out.get("request_id"),
    }


def _show(result: dict):
    print(f"\n[path: {result['path']}]\n{result['reply']}\n")


if __name__ == "__main__":
    args = sys.argv[1:]
    employee = "EMP001"
    if "--employee" in args:
        i = args.index("--employee")
        employee = args[i + 1]
        del args[i : i + 2]
    question = " ".join(args).strip()
    if question:
        _show(run_agent(employee, question))
    else:
        print(f"Chatting as {employee}. Type a question (empty line to quit).")
        while True:
            q = input("> ").strip()
            if not q:
                break
            _show(run_agent(employee, q))
