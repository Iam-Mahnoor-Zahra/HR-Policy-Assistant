"""The agent: a LangGraph workflow that decides what to do with each employee message.

    message -> classify -> sensitive -> offer to email HR (needs the employee's yes)
                        -> balance   -> leave balance tool
                        -> status    -> request status tool
                        -> holiday   -> holiday lookup
                        -> other     -> short help message (greetings, thanks, off-topic)
                        -> policy    -> policy search -> answer with citation
                                                      -> no source found -> offer to email HR

Escalation needs two "yes" answers: yes to "shall I email HR?", then yes to the draft.
Nothing is saved or sent before the second yes. The pending step travels with the chat.

Try it from the project root (the chat mode keeps the conversation, so the yes/no steps work):
    python -m src.agent --employee EMP003
    python -m src.agent --employee EMP003 "How many annual leave days do I have left?"
"""
import re
import sys
from datetime import date
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from src import emailer, tools
from src.llm import get_llm
from src.qa import answer_policy_question

# Safety net: these words always go to HR, without asking the model.
SENSITIVE_WORDS = (
    "harass", "bully", "bullied", "discriminat", "abuse", "assault",
    "threat", "retaliat", "unfair", "complaint", "grievance",
    "misbehav", "mistreat", "intimidat", "humiliat", "hostile",
)

ROUTER_PROMPT = """Classify the employee's message into one route. Today's date is {today}.

sensitive: complaints, harassment, bullying, discrimination, unfair treatment, conflicts with a manager or colleague, legal, medical or mental health matters, or a request to talk to a person.
balance: ONLY when the employee asks for their OWN current leave numbers (days left, used or total).
status: the employee asks about the status of their own leave request or HR request (pending, approved, rejected, open, replied).
holiday: the employee asks about company holidays: whether a date is a holiday, or which holidays are coming up.
policy: any question about company rules, limits, eligibility or procedures, or any other HR topic (pay, benefits, insurance, contracts), even if it mentions "I" or leave days. A later step checks whether the documents cover it.
other: ONLY greetings, thanks, questions about what the assistant can do, or topics clearly unrelated to work.

Examples:
- "How many annual leave days do I have left?" -> balance (annual, remaining)
- "What is my sick leave balance?" -> balance (sick, remaining)
- "How many sick days have I used?" -> balance (sick, used)
- "What is the status of my leave request 7?" -> status (request_id 7, kind leave)
- "Has HR replied to my request?" -> status (kind hr)
- "Is 9 November a holiday?" -> holiday (holiday_date 2026-11-09)
- "What are the next company holidays?" -> holiday
- "How many unused annual leave days can I carry forward?" -> policy (it asks about a rule)
- "How many annual leave days do employees get each year?" -> policy (it asks about a rule)
- "How long do I have to submit an expense claim?" -> policy
- "My manager is treating me badly" -> sensitive
- "What is my current salary?" -> policy (an HR topic, the document search will decide)
- "Hi" -> other
- "What can you do?" -> other
- "What is the weather today?" -> other

If the route is balance, also set leave_type (annual, sick or both) and detail (remaining, used or total).
If the route is status, set request_id only when a number is given, and request_kind (leave, hr or any).
If the route is holiday, set holiday_date (YYYY-MM-DD) only when one specific date is asked."""

# Second safety nets for the router. A model answer is downgraded to "policy" if the words do not fit.
OWN_HINTS = re.compile(r"\b(my|i have|have i|i've|left|remaining|balance|taken)\b", re.I)
LEAVE_HINTS = re.compile(r"\b(leave|leaves|annual|sick|vacation|holiday|holidays)\b", re.I)
STATUS_HINTS = re.compile(r"\b(status|pending|approved|rejected|request|requests|case|replied|reply|update)\b", re.I)
HOLIDAY_HINTS = re.compile(r"\b(holiday|holidays|day off|days off|closed|closure)\b", re.I)

# HR topics must never end up in the small-talk route.
HR_TOPICS = re.compile(
    r"\b(salary|salaries|pay|payslip|bonus|insurance|benefit|benefits|contract|resign|resignation|"
    r"terminate|termination|promotion|appraisal|increment|raise)\b",
    re.I,
)

# Plain greetings and thanks are answered without calling the model.
GREETING = re.compile(r"(hi+|hello|hey|salam|assalam[\w\s]*|thanks|thank you|thx|ok|okay)[\s!.?]*", re.I)

# Plain yes / no answers (used for the confirmation steps). A reply only counts if it is short,
# has no question mark, and every word is a known yes or no word, so "yes but what about sick leave?"
# is NOT a yes.
YES_START = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "haan", "ji", "confirm", "please",
             "plz", "pls", "send", "go", "do", "definitely", "absolutely"}
YES_WORDS = YES_START | {"it", "the", "email", "ahead", "kindly", "now", "that", "sounds", "good",
                         "fine", "looks", "great", "correct", "right", "is"}
NO_START = {"no", "n", "nope", "nah", "cancel", "stop", "don't", "dont", "do", "never", "nahi"}
NEGATIVE = {"no", "n", "nope", "nah", "cancel", "stop", "don't", "dont", "not", "never", "nahi"}
NO_WORDS = NO_START | {"not", "mind", "thanks", "thank", "you", "please", "plz", "pls", "send", "it",
                       "the", "email", "i", "want", "to", "need"}

# After a "no", these words bring the draft back ("can you send the email", "email HR").
REVIVE = re.compile(
    r"\b(send|email|mail|contact|forward)\b.*\b(email|mail|hr|it)\b|\b(email|contact)\s+hr\b", re.I
)

HELP_TEXT = (
    "I'm the HR Policy Assistant. I can answer questions about company HR policies, "
    "check your leave balance, tell you the status of your requests, look up company holidays, "
    "and point you to HR for sensitive matters. What would you like to know?"
)

REWRITE_PROMPT = """Rewrite the employee's latest message as one complete, standalone question. Use the chat history only to fill in missing details, for example what "that" or "and sick leave?" refers to.
Do not answer it. If the message already makes sense on its own, return it unchanged. Output only the question."""


class Route(BaseModel):
    route: Literal["sensitive", "balance", "status", "holiday", "policy", "other"]
    leave_type: Literal["annual", "sick", "both"] = "annual"
    detail: Literal["remaining", "used", "total"] = "remaining"
    request_id: int | None = None
    request_kind: Literal["leave", "hr", "any"] = "any"
    holiday_date: str | None = None


class AgentState(TypedDict, total=False):
    employee_id: str
    question: str
    original_question: str
    route: str
    leave_type: str
    detail: str
    request_id: int | None
    request_kind: str
    holiday_date: str | None
    escalation_reason: str
    reply: str
    path: str
    citations: list
    pending: dict


# ------------------------------------------------------------------ small helpers
def _asks_own_balance(question: str) -> bool:
    return bool(OWN_HINTS.search(question) and LEAVE_HINTS.search(question))


def _has_sensitive_word(question: str) -> bool:
    return any(word in question.lower() for word in SENSITIVE_WORDS)


def _fmt_date(value) -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{d.day} {d.strftime('%b %Y')}"  # no %-d, so it also works on Windows


def _parse_date(text):
    try:
        return date.fromisoformat(str(text)[:10]) if text else None
    except ValueError:
        return None


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


# ------------------------------------------------------------------------- nodes
def classify(state: AgentState) -> dict:
    question = state["question"]
    if GREETING.fullmatch(question.strip()):
        return {"route": "other"}
    if _has_sensitive_word(question):
        return {"route": "sensitive", "escalation_reason": "sensitive topic"}

    prompt = ROUTER_PROMPT.replace("{today}", date.today().isoformat())
    decision = get_llm().with_structured_output(Route).invoke([("system", prompt), ("human", question)])

    if decision.route == "sensitive":
        return {"route": "sensitive", "escalation_reason": "sensitive topic"}
    if decision.route == "other":
        return {"route": "policy" if HR_TOPICS.search(question) else "other"}
    if decision.route == "balance":
        if not _asks_own_balance(question):
            return {"route": "policy"}
        return {"route": "balance", "leave_type": decision.leave_type, "detail": decision.detail}
    if decision.route == "status":
        if not STATUS_HINTS.search(question):
            return {"route": "policy"}
        return {"route": "status", "request_id": decision.request_id, "request_kind": decision.request_kind}
    if decision.route == "holiday":
        if not HOLIDAY_HINTS.search(question):
            return {"route": "policy"}
        return {"route": "holiday", "holiday_date": decision.holiday_date}
    return {"route": "policy"}


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


HR_STATUS_TEXT = {
    "open": "logged, waiting for HR",
    "emailed": "emailed to HR",
    "resolved": "resolved by HR",
}


def _format_status(data: dict, request_id) -> str:
    lines = []
    for r in data["leave"]:
        lines.append(
            f"Leave request #{r['id']}: {r['leave_type']} leave, {_fmt_date(r['start_date'])} to "
            f"{_fmt_date(r['end_date'])} ({r['working_days']} working days), status: {r['status']}."
        )
    for r in data["hr"]:
        status = HR_STATUS_TEXT.get(r["status"], r["status"])
        lines.append(f"HR request #{r['id']}: {status}, sent on {_fmt_date(r['created_at'])}.")
    if not lines:
        if request_id:
            return f"I could not find request #{request_id} on your account."
        return "I could not find any requests on your account."
    header = "Here is what I found:" if request_id else "Your recent requests:"
    return header + "\n" + "\n".join(f"• {line}" for line in lines) + "\nSource: Request records"


def status_node(state: AgentState) -> dict:
    data = tools.get_request_status(
        state["employee_id"], state.get("request_id"), state.get("request_kind") or "any"
    )
    return {"reply": _format_status(data, state.get("request_id")), "path": "status"}


def holiday_node(state: AgentState) -> dict:
    day = _parse_date(state.get("holiday_date"))
    if day:
        holiday = tools.get_holiday(day)
        weekday = day.strftime("%A")
        if holiday:
            reply = f"Yes, {_fmt_date(day)} ({weekday}) is a company holiday: {holiday['name']}."
        elif day.weekday() >= 5:
            reply = f"{_fmt_date(day)} is a {weekday}, so it is a weekend. It is not a company holiday."
        else:
            reply = f"No, {_fmt_date(day)} ({weekday}) is not a company holiday."
    else:
        rows = tools.list_holidays(date.today(), limit=5)
        if rows:
            lines = [
                f"• {_fmt_date(r['holiday_date'])} ({date.fromisoformat(str(r['holiday_date'])[:10]).strftime('%A')}): {r['name']}"
                for r in rows
            ]
            reply = "Upcoming company holidays:\n" + "\n".join(lines)
        else:
            reply = "I could not find any upcoming company holidays."
    return {"reply": reply + "\nSource: Company holiday calendar", "path": "holiday"}


def other_node(state: AgentState) -> dict:
    return {"reply": HELP_TEXT, "path": "other"}


def escalate_node(state: AgentState) -> dict:
    """Step 1 of escalation: only OFFER to email HR. Nothing is saved or sent yet."""
    reason = state.get("escalation_reason", "sensitive topic")
    hr = emailer.hr_email_address()
    if reason == "sensitive topic":
        opening = "This needs attention from HR, and I cannot resolve it here."
    else:
        opening = "I could not find an answer to this in the HR policies."
    reply = (
        f"{opening} Would you like me to email HR about it? (yes or no)\n"
        f"You can also email HR yourself at {hr}."
    )
    pending = {
        "type": "escalate_offer",
        "question": state["question"],
        "original": state.get("original_question", state["question"]),
        "reason": reason,
    }
    return {"reply": reply, "path": "escalate_offer", "pending": pending}


# ----------------------------------------------------- the yes / no confirmation steps
DRAFT_PROMPT = """You help an employee write a short email to the HR team. Write ONLY the middle paragraph of the email, in the first person ("I"), as the employee.
Rules:
- Polite, calm and clear. 2 to 4 sentences.
- Use ONLY what the employee said. Do not add names, dates, accusations, feelings or details that are not in the message.
- Do not give advice and do not mention an AI or an assistant.
- {situation}
Output only the paragraph."""

SITUATIONS = {
    "sensitive topic": "The message is a concern about a workplace matter. Politely ask HR for help or a conversation.",
    "no source found": "The message is a question that the HR policy documents did not answer. Politely ask HR to answer it.",
}


def _draft_paragraph(question: str, reason: str):
    """Ask the model for the middle paragraph of the email. Returns None if it fails (a plain one is used)."""
    situation = SITUATIONS.get(reason, SITUATIONS["sensitive topic"])
    try:
        reply = get_llm().invoke(
            [("system", DRAFT_PROMPT.replace("{situation}", situation)),
             ("human", f"Employee's message: {question}")]
        )
        text = (reply.content or "").strip()
    except Exception as e:
        print(f"[warning] could not draft the email paragraph: {e}")
        return None
    return text if text and len(text) <= 700 else None


def _yes_no(text: str):
    if "?" in text:
        return None
    words = re.findall(r"[a-z']+", text.lower())
    if not words or len(words) > 5:
        return None
    if words[0] in NO_START and all(w in NO_WORDS for w in words) and any(w in NEGATIVE for w in words):
        return "no"
    if words[0] in YES_START and all(w in YES_WORDS for w in words):
        return "yes"
    return None


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.split("\n"))


def _declined(pending: dict, path: str = "escalate_declined") -> dict:
    """The employee said no. The offer stays available for ONE more message ("can you send the email")."""
    hr = emailer.hr_email_address()
    reply = (
        f"No problem. I have not sent anything. You can email HR yourself at {hr}, "
        "or just say \"send the email\" if you change your mind."
    )
    dormant = {**pending, "type": "escalate_declined"}
    return {"reply": reply, "path": path, "citations": [], "request_id": None, "pending": dormant}


def _draft_reply(employee_id: str, pending: dict) -> dict:
    employee = tools.get_employee(employee_id)
    if employee is None:
        return {"reply": "I could not find your employee record, so I cannot prepare the email.",
                "path": "escalate_done", "citations": [], "request_id": None, "pending": None}
    original = pending.get("original", pending["question"])
    paragraph = _draft_paragraph(pending["question"], pending["reason"])
    subject, body = tools.build_escalation_email(employee, original, pending["reason"], paragraph)
    reply = (
        "Here is the email I would send to HR:\n\n"
        f"**Subject:** {subject}\n\n{_quote(body)}\n\n"
        "A request ID is added when it is sent. Shall I send it? (yes or no)"
    )
    new_pending = {**pending, "type": "escalate_confirm", "subject": subject, "body": body}
    return {"reply": reply, "path": "escalate_draft", "citations": [], "request_id": None,
            "pending": new_pending}


def _handle_pending(employee_id: str, text: str, pending: dict):
    """Answer a yes or no to the last question. Returns None if the message is something else."""
    answer = _yes_no(text)
    kind = pending["type"]

    if kind == "escalate_declined":
        # one more chance: the employee changed their mind
        if answer == "yes" or REVIVE.search(text):
            return _draft_reply(employee_id, pending)
        if answer == "no":
            return {"reply": "Okay, I will not send anything.", "path": "escalate_done",
                    "citations": [], "request_id": None, "pending": None}
        return None

    if answer is None:
        return None  # the employee moved on, so the pending step is dropped and nothing is sent

    if kind == "escalate_offer":
        return _declined(pending) if answer == "no" else _draft_reply(employee_id, pending)

    if kind == "escalate_confirm":
        if answer == "no":
            return _declined(pending)
        original = pending.get("original", pending["question"])
        info = tools.send_escalation(
            employee_id, original, pending["reason"], pending["subject"], pending["body"]
        )
        hr, rid = info["hr_email"], info["request_id"]
        if rid and info["email_sent"]:
            reply = f"Sent. HR has your request (ID {rid}). You can also email HR at {hr}."
        elif rid:
            reply = (f"I saved your request (ID {rid}) but could not send the email. "
                     f"Please email HR at {hr} and quote ID {rid}.")
        elif info["email_sent"]:
            reply = f"The email was sent to HR, but I could not save a record of it. You can also email HR at {hr}."
        else:
            reply = f"I could not send the email or save your request. Please email HR directly at {hr}."
        return {"reply": reply, "path": "escalate_sent", "citations": [], "request_id": rid, "pending": None}

    return None


# ------------------------------------------------------------------------- graph
def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", classify)
    g.add_node("policy", policy_node)
    g.add_node("balance", balance_node)
    g.add_node("status", status_node)
    g.add_node("holiday", holiday_node)
    g.add_node("escalate", escalate_node)
    g.add_node("other", other_node)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        lambda s: s["route"],
        {
            "sensitive": "escalate",
            "balance": "balance",
            "status": "status",
            "holiday": "holiday",
            "policy": "policy",
            "other": "other",
        },
    )
    g.add_conditional_edges(
        "policy",
        lambda s: "done" if s.get("path") == "policy" else "escalate",
        {"done": END, "escalate": "escalate"},
    )
    for name in ("balance", "status", "holiday", "other", "escalate"):
        g.add_edge(name, END)
    return g.compile()


graph = _build_graph()


def run_agent(employee_id: str, question: str, history: list | None = None, pending: dict | None = None) -> dict:
    """Handle one message. Returns {"reply", "path", "citations", "request_id", "pending"}.

    history: earlier messages of this chat as [{"role": "user" or "assistant", "content": "..."}].
    pending: the unanswered yes/no step of this chat (returned by the previous call), or None.
    Keep the returned "pending" with the chat and pass it back on the next message.
    """
    if pending:
        outcome = _handle_pending(employee_id, question, pending)
        if outcome is not None:
            return outcome
    standalone = _standalone_question(question, history)
    out = graph.invoke({"employee_id": employee_id, "question": standalone, "original_question": question})
    return {
        "reply": out["reply"],
        "path": out["path"],
        "citations": out.get("citations", []),
        "request_id": None,
        "pending": out.get("pending"),
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
    first = " ".join(args).strip()
    chat_history, chat_pending = [], None
    print(f"Chatting as {employee}. Type a message (empty line to quit).")
    while True:
        q = first or input("> ").strip()
        first = ""
        if not q:
            break
        result = run_agent(employee, q, history=chat_history, pending=chat_pending)
        chat_pending = result["pending"]
        chat_history += [{"role": "user", "content": q}, {"role": "assistant", "content": result["reply"]}]
        _show(result)
