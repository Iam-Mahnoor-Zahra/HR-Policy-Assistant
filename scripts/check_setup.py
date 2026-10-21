"""Quick Day 1 check. Run from the project root:  python scripts/check_setup.py"""
import csv
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
problems = 0

print("1) Environment variables")
for var in ["LLM_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "APP_PASSWORD"]:
    if os.getenv(var):
        print(f"   [ok] {var} is set")
    else:
        print(f"   [missing] {var}")
        problems += 1

print("2) Local data files")
policies = sorted(Path("data/policies").glob("*.md"))
print(f"   [{'ok' if len(policies) >= 5 else 'check'}] {len(policies)} policy files found")
with open("eval/test_questions.csv", encoding="utf-8") as f:
    print(f"   [ok] {len(list(csv.DictReader(f)))} test questions found")

print("3) Supabase connection")
try:
    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    result = client.table("employees").select("*", count="exact").execute()
    print(f"   [ok] employees table has {result.count} rows (expected 10)")
    client.table("escalations").select("*", count="exact").limit(1).execute()
    print("   [ok] escalations table is reachable")
except Exception as e:
    print(f"   [problem] {type(e).__name__}: {e}")
    problems += 1

print()
print("All good." if problems == 0 else f"{problems} item(s) need attention.")
