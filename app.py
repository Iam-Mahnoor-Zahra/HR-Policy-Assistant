"""HR Policy Assistant: the Streamlit app.

Run from the project root:   streamlit run app.py
"""
import hmac
import html
import os
from datetime import date
from pathlib import Path

import streamlit as st


def _load_secrets_into_env():
    """On hosting platforms, settings live in st.secrets. Copy them into the environment."""
    try:
        for key in st.secrets:
            value = st.secrets[key]
            if isinstance(value, (str, int, float, bool)):
                os.environ.setdefault(key, str(value))
    except Exception:
        pass  # no secrets file when running locally: the .env file is used instead


_load_secrets_into_env()

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src import db, tools  # noqa: E402
from src.agent import run_agent  # noqa: E402

MAX_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "500"))
HR_EMAIL = os.getenv("HR_EMAIL", "hr@examplecorp.com")
EXAMPLES = [
    "How many leave days can I carry forward?",
    "How many annual leave days do I have left?",
    "What is the daily meal limit on a business trip?",
]

st.set_page_config(page_title="HR Policy Assistant", page_icon="🤖", layout="wide")

# Layout styling. Colors come from the theme (light or dark), so both modes work.
STYLE = """
<style>
:root { --line: color-mix(in srgb, currentColor 14%, transparent); --soft: color-mix(in srgb, currentColor 6%, transparent); }

/* ---------- page and buttons (colors follow the light or dark theme) ---------- */
.block-container { padding-top: 2rem; padding-bottom: 5rem; max-width: 1100px; }
h1, h2, h3, h4 { letter-spacing: -0.01em; }
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button, [data-testid="stFormSubmitButton"] button {
    border-radius: 10px; min-height: 2.5rem; font-weight: 500; transition: border-color .15s, background .15s, transform .05s;
}
[data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover,
[data-testid="stFormSubmitButton"] button:hover { border-color: #6366F1; }
[data-testid="stButton"] button:active { transform: scale(0.98); }
[data-testid="stTextInput"] input { border-radius: 10px; }
[data-testid="stTabs"] [role="tab"] { padding: 0.5rem 1rem; }

/* ---------- chat bubbles: employee on the right, assistant on the left with a bot avatar ---------- */
[class*="st-key-msg_user_"] > [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"]) {
    width: fit-content; max-width: 75%; margin-left: auto;
}
[class*="st-key-msg_bot_"] > [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"]) {
    width: fit-content; max-width: 85%;
}
[class*="st-key-msg_user_"] [data-testid="stMarkdown"] {
    background: rgba(99, 102, 241, 0.22); border-radius: 18px 18px 4px 18px; padding: 0.65rem 1rem;
}
[class*="st-key-msg_bot_"] [data-testid="stMarkdown"] {
    background: var(--soft); border: 1px solid var(--line);
    border-radius: 18px 18px 18px 4px; padding: 0.65rem 1rem;
}
[class*="st-key-msg_bot_"] { position: relative; padding-left: 46px; }
[class*="st-key-msg_bot_"]::before {
    content: "🤖"; position: absolute; left: 0; top: 2px; width: 34px; height: 34px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 18px;
    background: rgba(99, 102, 241, 0.16); border: 1px solid var(--line);
}
[class*="st-key-msg_user_"] [data-testid="stMarkdown"] p,
[class*="st-key-msg_bot_"] [data-testid="stMarkdown"] p { margin-bottom: 0; line-height: 1.55; }
[class*="st-key-msg_user_"] [data-testid="stMarkdownContainer"],
[class*="st-key-msg_bot_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0 !important; }
/* lists, code and long words inside messages */
[class*="st-key-msg_"] [data-testid="stMarkdown"] { overflow-wrap: anywhere; }
[class*="st-key-msg_"] ul, [class*="st-key-msg_"] ol { margin: 0.35rem 0 0.35rem 0.2rem; padding-left: 1.2rem; }
[class*="st-key-msg_"] li { margin: 0.15rem 0; }
[class*="st-key-msg_"] pre { border-radius: 10px; overflow-x: auto; border: 1px solid var(--line); }
[class*="st-key-msg_"] code { font-size: 0.85em; border-radius: 6px; }
/* source citations */
[class*="st-key-msg_bot_"] [data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 12px; margin-top: 0.4rem; }
[class*="st-key-msg_bot_"] [data-testid="stDownloadButton"] button { min-height: 2.1rem; font-size: 0.85rem; margin-top: 0.4rem; }

/* ---------- sidebar: header on top, scrollable chats in the middle, user card pinned to the bottom ---------- */
[data-testid="stSidebar"] { border-right: 1px solid var(--line); }
[data-testid="stSidebarContent"] { display: flex; flex-direction: column; height: 100%; }
[data-testid="stSidebarUserContent"] { flex: 1 1 auto; display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"] > div { flex: 1 1 auto; display: flex; flex-direction: column; }
[data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] { flex: 1 1 auto; }
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-side_bottom"]) { margin-top: auto; }
.st-key-side_history, .st-key-side_history > [data-testid="stVerticalBlock"] {
    height: 360px !important; height: calc(100dvh - 400px) !important; min-height: 150px;
}
.st-key-side_history [data-testid="stVerticalBlock"] { gap: 0.15rem; }
.st-key-side_history [data-testid="stButton"] button {
    min-height: 2.1rem; padding: 0.2rem 0.6rem; font-size: 0.9rem; justify-content: flex-start; text-align: left;
}
.st-key-side_history [data-testid="stButton"] button p { text-align: left; }
.user-card { display: flex; align-items: center; gap: 0.7rem; padding: 0.3rem 0; }
.avatar { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-weight: 700; color: #fff; background: #4F46E5; flex: 0 0 auto; }
.uname { font-weight: 600; line-height: 1.2; }
.uid { font-size: 0.8rem; opacity: 0.65; }

/* ---------- welcome and login ---------- */
.welcome { text-align: center; margin: 10vh 0 1.5rem 0; }
.welcome h2 { margin-bottom: 0.2rem; }
.welcome p { opacity: 0.7; }
.bot-badge { font-size: 2.6rem; line-height: 1; margin-bottom: 0.5rem; }

/* ---------- HR page ---------- */
.st-key-hr_header [data-testid="stHorizontalBlock"] { align-items: center; }
.st-key-hr_header h1 { padding: 0; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; }
[class*="st-key-req_"] [data-testid="stHorizontalBlock"] { max-width: 360px; }

/* ---------- phones ---------- */
@media (max-width: 640px) {
    .block-container { padding: 1rem 0.8rem 5rem; }
    .welcome { margin: 4vh 0 1rem 0; }
    [data-testid="stButton"] button, [data-testid="stDownloadButton"] button,
    [data-testid="stFormSubmitButton"] button { min-height: 2.75rem; }
    [class*="st-key-msg_user_"] > [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"]) { max-width: 92%; }
    [class*="st-key-msg_bot_"] > [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"]) { max-width: 100%; }
    [class*="st-key-msg_bot_"] { padding-left: 40px; }
    [class*="st-key-msg_bot_"]::before { width: 30px; height: 30px; font-size: 16px; }
    /* Approve / Reject and the HR header stay on one row instead of stacking */
    [class*="st-key-req_"] [data-testid="stHorizontalBlock"], .st-key-hr_header [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important; max-width: 100%;
    }
    [class*="st-key-req_"] [data-testid="stColumn"] { min-width: 0 !important; flex: 1 1 0 !important; width: auto !important; }
    .st-key-hr_header [data-testid="stColumn"]:first-child { min-width: 0 !important; flex: 1 1 auto !important; width: auto !important; }
    .st-key-hr_header [data-testid="stColumn"]:last-child { flex: 0 0 auto !important; width: auto !important; min-width: 96px !important; }
    .st-key-hr_header h1 { font-size: 1.7rem; }
}
</style>
"""


@st.cache_resource(show_spinner="Preparing the knowledge base (first start only)...")
def prepare_knowledge_base():
    """Build the policy index if it does not exist yet, and load it into memory once."""
    if os.getenv("SKIP_KB_SETUP") == "1":  # used by the automatic tests
        return True
    if not Path("chroma_db").exists():
        from src.ingest import main as build_index

        build_index()
    from src.qa import _cached_store

    _cached_store()
    return True


def wide_button(label, **kwargs):
    """A full-width button that works on both newer and older Streamlit versions."""
    try:
        return st.button(label, width="stretch", **kwargs)
    except TypeError:
        return st.button(label, use_container_width=True, **kwargs)


# ------------------------------------------------------------ chat bookkeeping
def new_chat():
    chat_id = st.session_state.next_id
    st.session_state.next_id += 1
    st.session_state.chats[chat_id] = {"title": "New chat", "messages": [], "pending": None, "db_id": None}
    st.session_state.order.insert(0, chat_id)
    st.session_state.current = chat_id


def start_session(employee: dict):
    st.session_state.employee = {"id": employee["employee_id"], "name": employee["name"]}
    st.session_state.chats = {}
    st.session_state.order = []
    st.session_state.next_id = 1
    try:
        saved = db.fetch_chats(employee["employee_id"])  # this employee's own chats, newest first
    except Exception as e:
        print(f"[warning] could not load the saved chats: {e}")
        saved = []
    for row in reversed(saved):  # oldest first, so the newest ends up at the top of the list
        chat_id = st.session_state.next_id
        st.session_state.next_id += 1
        # a yes/no step that was open when the employee left is not brought back
        st.session_state.chats[chat_id] = {"title": row["title"], "messages": row["messages"] or [],
                                           "pending": None, "db_id": row["id"]}
        st.session_state.order.insert(0, chat_id)
    new_chat()


def save_chat(employee_id: str, chat: dict):
    """Keep the chat in the database so it is still there after logout. A failure never breaks the chat."""
    try:
        if chat.get("db_id"):
            db.update_chat(chat["db_id"], employee_id, chat["title"], chat["messages"])
        else:
            chat["db_id"] = db.insert_chat(employee_id, chat["title"], chat["messages"])
    except Exception as e:
        print(f"[warning] could not save the chat: {e}")


def short(text: str, limit: int = 30) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------- login screen
def login_screen():
    app_password = os.getenv("APP_PASSWORD", "")
    if not app_password:
        st.error("The app password is not set. Add APP_PASSWORD to your .env file or hosting secrets.")
        st.stop()

    _, middle, _ = st.columns([1, 1.4, 1])
    with middle:
        st.markdown(
            "<div class='welcome' style='margin-top:8vh'><div class='bot-badge'>🤖</div><h2>HR Policy Assistant</h2>"
            "<p>Sign in to ask about HR policies, check your leave balance, "
            "or get pointed to HR.</p></div>",
            unsafe_allow_html=True,
        )
        tab_employee, tab_hr = st.tabs(["Employee", "HR"])
        with tab_employee:
            with st.form("login"):
                employee_id = st.text_input("Employee ID", placeholder="EMP001")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in")

            if submitted:
                emp_id = employee_id.strip().upper()
                password_ok = hmac.compare_digest(password.encode(), app_password.encode())
                try:
                    employee = db.fetch_employee(emp_id) if emp_id else None
                except Exception as e:
                    print(f"[error] login lookup failed: {e}")
                    st.error("Could not reach the database. Please try again.")
                    return
                if password_ok and employee:
                    start_session(employee)
                    st.rerun()
                else:
                    st.error("Invalid employee ID or password.")

        with tab_hr:
            with st.form("hr_login"):
                hr_password = st.text_input("HR password", type="password")
                hr_submitted = st.form_submit_button("Open HR page")
            if hr_submitted:
                expected = os.getenv("HR_PASSWORD", "")
                if not expected:
                    st.error("The HR password is not set. Add HR_PASSWORD to your .env file or hosting secrets.")
                elif hmac.compare_digest(hr_password.encode(), expected.encode()):
                    st.session_state.hr_ok = True
                    st.rerun()
                else:
                    st.error("Invalid HR password.")


# ----------------------------------------------------------------------- HR page
def fmt_day(value) -> str:
    d = date.fromisoformat(str(value)[:10])
    return f"{d.day} {d.strftime('%b %Y')}"  # no %-d, so it also works on Windows


def resolve(request_id: int):
    try:
        result = tools.resolve_escalation(request_id)
    except Exception as e:
        print(f"[error] resolving failed: {e}")
        result = {"ok": False, "message": "Something went wrong. Please check the request and try again."}
    st.session_state.hr_notice = (result["ok"], result["message"])
    st.rerun()


def decide(request_id: int, approve: bool):
    try:
        result = tools.decide_leave_request(request_id, approve)
    except Exception as e:
        print(f"[error] decision failed: {e}")
        result = {"ok": False, "message": "Something went wrong. Please check the request and try again."}
    st.session_state.hr_notice = (result["ok"], result["message"])
    st.rerun()


try:
    check_every_30s = st.fragment(run_every="30s")
except (AttributeError, TypeError):  # very old Streamlit: no automatic check

    def check_every_30s(func):
        return func


@check_every_30s
def watch_for_new_requests():
    """Draws nothing. Every 30 seconds it compares the pending request IDs with what the page shows,
    and reloads the page only when they differ, so the screen does not flicker."""
    try:
        ids = tuple(r["id"] for r in tools.hr_list_leave_requests(["pending"]))
        esc_ids = tuple(r["id"] for r in tools.hr_list_escalations(["open", "emailed"]))
    except Exception as e:
        print(f"[warning] could not check for new requests: {e}")
        return
    if ids != st.session_state.get("hr_seen_ids") or esc_ids != st.session_state.get("hr_seen_esc_ids"):
        st.rerun()


def hr_screen():
    with st.sidebar:
        st.markdown("#### 🤖 HR Policy Assistant")
        st.caption("Leave approvals and escalations")

    with st.container(key="hr_header"):
        title_col, logout_col = st.columns([5, 1])
        with title_col:
            st.title("HR page")
        with logout_col:
            if wide_button("Log out", key="hr_logout"):
                st.session_state.clear()
                st.rerun()
    notice = st.session_state.pop("hr_notice", None)
    if notice:
        (st.success if notice[0] else st.warning)(notice[1])

    try:
        pending = tools.hr_list_leave_requests(["pending"])
        decided = tools.hr_list_leave_requests(["approved", "rejected"], limit=10, newest_first=True)
    except Exception as e:
        print(f"[error] could not load requests: {e}")
        st.error("Could not load the requests. Please try again.")
        return
    st.session_state.hr_seen_ids = tuple(r["id"] for r in pending)

    try:
        open_esc = tools.hr_list_escalations(["open", "emailed"])
        resolved_esc = tools.hr_list_escalations(["resolved"], limit=10)
    except Exception as e:
        print(f"[error] could not load escalations: {e}")
        open_esc, resolved_esc = None, None
    st.session_state.hr_seen_esc_ids = tuple(r["id"] for r in open_esc or [])

    # the tab names stay the same, so the open tab is kept when the page reloads
    tab_leave, tab_esc = st.tabs(["Leave requests", "Escalations"])
    with tab_leave:
        show_requests(pending, decided)
    with tab_esc:
        show_escalations(open_esc, resolved_esc)
    st.caption("New requests appear by themselves (checked every 30 seconds).")
    watch_for_new_requests()


def show_requests(pending: list, decided: list):
    st.subheader(f"Waiting for a decision ({len(pending)})")
    if not pending:
        st.info("No pending requests.")
    for r in pending:
        with st.container(border=True, key=f"req_{r['id']}"):
            st.markdown(f"**Request #{r['id']}: {html.escape(r['name'])} ({html.escape(r['employee_id'])})**")
            days = r["working_days"]
            st.write(
                f"{r['leave_type'].capitalize()} leave, {fmt_day(r['start_date'])} to "
                f"{fmt_day(r['end_date'])}, {days} working day{'s' if days != 1 else ''}"
            )
            approve_col, reject_col = st.columns(2)
            if approve_col.button("Approve", key=f"approve_{r['id']}", type="primary"):
                decide(r["id"], True)
            if reject_col.button("Reject", key=f"reject_{r['id']}"):
                decide(r["id"], False)

    if decided:
        st.subheader("Recent decisions")
        with st.container(height=250, border=True, key="recent_decisions"):
            for r in decided:
                icon = "✅" if r["status"] == "approved" else "❌"
                with st.container(border=True):
                    st.markdown(
                        f"{icon} #{r['id']} {r['name']}, {r['leave_type']} leave, {fmt_day(r['start_date'])} to "
                        f"{fmt_day(r['end_date'])}: **{r['status']}**"
                    )


def show_escalations(open_rows, resolved_rows):
    if open_rows is None:
        st.error("Could not load the escalations. Please try again.")
        return
    st.subheader(f"Open ({len(open_rows)})")
    if not open_rows:
        st.info("No open escalations.")
    for r in open_rows:
        with st.container(border=True, key=f"esc_{r['id']}"):
            st.markdown(f"**HR request #{r['id']}: {html.escape(r['name'])} ({html.escape(r['employee_id'])})**")
            st.caption(f"{fmt_day(r['created_at'])} | {r['reason']} | {r['status']}")
            st.write(r.get("question") or "")
            if st.button("Mark as resolved", key=f"resolve_{r['id']}", type="primary"):
                resolve(r["id"])

    if resolved_rows:
        st.subheader("Recently resolved")
        with st.container(height=300, border=True, key="recent_resolved"):
            for r in resolved_rows:
                with st.container(border=True):
                    st.markdown(f"✅ #{r['id']} {r['name']}, {r['reason']}: **resolved**")


# ----------------------------------------------------------------- chat screen
def show_message(chat_id: int, index: int, msg: dict):
    role = "user" if msg["role"] == "user" else "bot"
    with st.container(key=f"msg_{role}_{chat_id}_{index}"):
        st.markdown(msg["content"].replace("\n", "  \n"))
        citations = msg.get("citations") or []
        shown_files = set()
        for c in citations:
            if c["file"] in shown_files:
                continue
            shown_files.add(c["file"])
            path = Path(c["path"])
            if path.exists():
                st.download_button(
                    f"Download {c['policy']}",
                    data=path.read_bytes(),
                    file_name=c["file"],
                    mime="text/markdown",
                    key=f"download_{chat_id}_{index}_{c['file']}",
                )
        if citations:
            with st.expander("Show the policy text"):
                for c in citations:
                    st.markdown(f"**{c['label']}**")
                    st.write(c["excerpt"])


def sidebar():
    employee = st.session_state.employee
    with st.sidebar:
        with st.container(key="side_top"):
            st.markdown("#### 🤖 HR Policy Assistant")
            if wide_button("＋ New chat", key="new_chat", type="primary"):
                if st.session_state.chats[st.session_state.current]["messages"]:
                    new_chat()
                st.rerun()
            st.caption("Previous chats")

        # only this list scrolls: the header above and the user card below stay in place
        with st.container(height=360, border=False, key="side_history"):
            shown = 0
            for chat_id in st.session_state.order:
                chat = st.session_state.chats[chat_id]
                if not chat["messages"]:
                    continue
                shown += 1
                active = chat_id == st.session_state.current
                if wide_button(
                    short(chat["title"]),
                    key=f"open_{chat_id}",
                    type="secondary" if active else "tertiary",
                ):
                    st.session_state.current = chat_id
                    st.rerun()
            if not shown:
                st.caption("No chats yet.")

        with st.container(key="side_bottom"):
            st.divider()
            initial = html.escape(employee["name"][:1].upper())
            st.markdown(
                f"<div class='user-card'><div class='avatar'>{initial}</div><div>"
                f"<div class='uname'>{html.escape(employee['name'])}</div>"
                f"<div class='uid'>{html.escape(employee['id'])}</div></div></div>",
                unsafe_allow_html=True,
            )
            if wide_button("Log out", key="logout"):
                st.session_state.clear()
                st.rerun()


def chat_screen():
    employee = st.session_state.employee
    sidebar()

    chat_id = st.session_state.current
    chat = st.session_state.chats[chat_id]
    messages = chat["messages"]

    clicked = None
    if not messages:
        st.markdown(
            f"<div class='welcome'><div class='bot-badge'>🤖</div><h2>Hello, {html.escape(employee['name'])}</h2>"
            "<p>Ask about HR policies or your leave. Answers show their source.</p></div>",
            unsafe_allow_html=True,
        )
        _, middle, _ = st.columns([1, 2, 1])
        with middle:
            for i, example in enumerate(EXAMPLES):
                if wide_button(example, key=f"example_{i}"):
                    clicked = example

    for i, msg in enumerate(messages):
        show_message(chat_id, i, msg)

    prompt = st.chat_input("Ask a question about HR policies or your leave") or clicked
    if not prompt:
        return
    prompt = prompt.strip()
    if len(prompt) > MAX_CHARS:
        st.warning(f"Please keep your question under {MAX_CHARS} characters (yours has {len(prompt)}).")
        return

    history = [{"role": m["role"], "content": m["content"]} for m in messages]
    user_msg = {"role": "user", "content": prompt}
    show_message(chat_id, len(messages), user_msg)
    messages.append(user_msg)
    if chat["title"] == "New chat":
        chat["title"] = prompt

    with st.spinner("Thinking..."):
        try:
            result = run_agent(employee["id"], prompt, history=history, pending=chat.get("pending"))
            reply = {
                "role": "assistant",
                "content": result["reply"],
                "citations": result["citations"],
                "path": result["path"],
            }
            chat["pending"] = result.get("pending")  # an unanswered yes/no step stays with this chat
        except Exception as e:
            print(f"[error] agent failed: {e}")
            reply = {
                "role": "assistant",
                "content": f"Sorry, something went wrong. Please try again, or email HR at {HR_EMAIL}.",
            }
    show_message(chat_id, len(messages), reply)
    messages.append(reply)
    save_chat(employee["id"], chat)
    st.rerun()


# ------------------------------------------------------------------------ main
st.markdown(STYLE, unsafe_allow_html=True)
prepare_knowledge_base()

if st.session_state.get("hr_ok"):
    hr_screen()
elif "employee" not in st.session_state:
    login_screen()
else:
    chat_screen()
