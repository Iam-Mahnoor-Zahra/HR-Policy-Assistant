"""Run all test questions through the full agent and check the path taken.

From the project root:   python scripts/run_agent_tests.py
Checks:
  policy    -> path is "policy" and the cited source matches the expected one
  balance   -> path is "balance" and the expected number appears in the reply
  escalate  -> path is "escalate" and the reply contains the HR email
Note: every escalate question adds a row to the escalations table in Supabase.
Clear them afterwards in the SQL Editor with:  delete from escalations;
"""
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import run_agent  # noqa: E402

HR_EMAIL = os.getenv("HR_EMAIL", "hr@examplecorp.com")


def main():
    with open("eval/test_questions.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    passed = 0
    for r in rows:
        employee = r["employee_id"] or "EMP001"
        res = run_agent(employee, r["question"])
        route = r["expected_route"]
        if route == "policy":
            cited = [f"{c['file']} {c['section']}" for c in res["citations"]]
            good = res["path"] == "policy" and r["expected_source"] in cited
        elif route == "balance":
            number = re.findall(r"\d+", r["expected_answer"])[0]
            good = res["path"] == "balance" and number in re.findall(r"\d+", res["reply"])
        else:
            good = res["path"] == "escalate" and HR_EMAIL in res["reply"]
        passed += good
        print(f"[{'PASS' if good else 'FAIL'}] #{r['id']} ({route}) {r['question']}")
        if not good:
            print(f"        path: {res['path']}   expected route: {route}")
            print(f"        reply: {res['reply']}")
    print(f"\n{passed} of {len(rows)} passed")


if __name__ == "__main__":
    main()
