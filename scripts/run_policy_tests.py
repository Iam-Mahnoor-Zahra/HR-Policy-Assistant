"""Run the policy and escalation test questions through the Q&A function.

From the project root:   python scripts/run_policy_tests.py
It checks that the cited source matches the expected one (policy questions) and that
questions with no source in the policies are NOT answered (escalate questions).
You still read the answers yourself to judge the wording. Balance questions are skipped (Day 3).
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.qa import answer_policy_question  # noqa: E402


def main():
    with open("eval/test_questions.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["expected_route"] in ("policy", "escalate")]

    passed = 0
    for r in rows:
        res = answer_policy_question(r["question"])
        cited = [f"{c['file']} {c['section']}" for c in res["citations"]]
        if r["expected_route"] == "policy":
            good = r["expected_source"] in cited
        else:
            good = not res["found"]
        passed += good
        print(f"[{'PASS' if good else 'FAIL'}] #{r['id']} {r['question']}")
        if res["found"]:
            print(f"        answer:   {res['answer']}")
            print(f"        cited:    {', '.join(cited)}")
        else:
            print(f"        no answer ({res['reason']})")
        if not good:
            print(f"        expected: {r['expected_source'] or 'no answer (escalate)'}")
    print(f"\n{passed} of {len(rows)} passed")


if __name__ == "__main__":
    main()
