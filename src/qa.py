"""Policy Q&A: find relevant policy text, write a short answer, return citations.

Try it from the project root:
    python -m src.qa "How many unused annual leave days can I carry forward?"
    python -m src.qa --debug "What dental insurance is offered?"   (shows search distances)
Run without a question to chat in the terminal.
"""
import os
import sys
from functools import lru_cache

from pydantic import BaseModel, Field

from src.llm import get_llm
from src.vectorstore import get_store

TOP_K = int(os.getenv("TOP_K", "3"))
# Lower distance = closer match. Chunks farther than this are treated as "not relevant".
# Calibrate with: python -m src.qa --debug "<question>"
MAX_DISTANCE = float(os.getenv("MAX_DISTANCE", "0.65"))
POLICY_FOLDER = "data/policies"

SYSTEM_PROMPT = """You are an HR policy assistant for ExampleCorp.
Answer the employee's question using ONLY the numbered sources provided.
- Write 1 to 3 short sentences in simple English.
- If the sources do not contain the answer, set answerable to false.
- List the numbers of the sources you actually used.
- Never use outside knowledge and never guess."""


class PolicyAnswer(BaseModel):
    answerable: bool = Field(description="True only if the sources contain the answer")
    answer: str = Field(description="Short answer based only on the sources")
    used_sources: list[int] = Field(description="Numbers of the sources used for the answer")


@lru_cache(maxsize=1)
def _cached_store():
    """Build the store once, so the embedding model is loaded only once per run."""
    return get_store()


def search_policies(question: str, k: int = TOP_K):
    """Return (chunk, distance) pairs that are close enough to the question."""
    hits = _cached_store().similarity_search_with_score(question, k=k)
    return [(doc, score) for doc, score in hits if score <= MAX_DISTANCE]


def _chunk_text(doc) -> str:
    return doc.page_content.split("\n", 1)[1] if "\n" in doc.page_content else doc.page_content


def answer_policy_question(question: str) -> dict:
    """Return {"found", "answer", "citations", "reason"}.

    Each citation has: label, policy, section, title, file, path, excerpt.
    Citations come from the stored metadata, never from the model's own words.
    """
    hits = search_policies(question)
    if not hits:
        return {"found": False, "answer": "", "citations": [], "reason": "no relevant policy text"}

    sources = "\n\n".join(
        f"[{i}] {d.metadata['policy_name']}, Section {d.metadata['section']} ({d.metadata['title']})\n{_chunk_text(d)}"
        for i, (d, _) in enumerate(hits, start=1)
    )
    structured_llm = get_llm().with_structured_output(PolicyAnswer)
    result = structured_llm.invoke(
        [("system", SYSTEM_PROMPT), ("human", f"Sources:\n{sources}\n\nQuestion: {question}")]
    )
    if not result.answerable:
        return {"found": False, "answer": "", "citations": [], "reason": "sources do not answer the question"}

    used = [i for i in dict.fromkeys(result.used_sources) if 1 <= i <= len(hits)]
    if not used:
        used = [1]  # the model gave no valid source number, so cite the closest chunk

    citations = []
    for i in used:
        d = hits[i - 1][0]
        m = d.metadata
        citations.append(
            {
                "label": f"{m['policy_name']}, Section {m['section']} ({m['title']})",
                "policy": m["policy_name"],
                "section": m["section"],
                "title": m["title"],
                "file": m["file_name"],
                "path": f"{POLICY_FOLDER}/{m['file_name']}",
                "excerpt": _chunk_text(d),
            }
        )
    return {"found": True, "answer": result.answer.strip(), "citations": citations, "reason": ""}


def _print_result(r: dict):
    if not r["found"]:
        print(f"\nNo answer found ({r['reason']}). This would be escalated to HR.\n")
        return
    print(f"\nAnswer: {r['answer']}")
    for c in r["citations"]:
        print(f"Source: {c['label']}  [{c['file']}]")
    print()


def _debug(question: str):
    print("\nClosest chunks (lower distance = closer):")
    for doc, score in _cached_store().similarity_search_with_score(question, k=5):
        flag = "keep" if score <= MAX_DISTANCE else "drop"
        m = doc.metadata
        print(f"  {score:.3f} [{flag}]  {m['file_name']} {m['section']} {m['title']}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    debug = "--debug" in args
    question = " ".join(a for a in args if a != "--debug").strip()
    if question:
        if debug:
            _debug(question)
        _print_result(answer_policy_question(question))
    else:
        print("Policy Q&A. Type a question (empty line to quit).")
        while True:
            q = input("> ").strip()
            if not q:
                break
            if debug:
                _debug(q)
            _print_result(answer_policy_question(q))
