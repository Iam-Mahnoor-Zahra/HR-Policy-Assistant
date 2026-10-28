"""Send one test email, to check your email settings.

From the project root:
    python scripts/send_test_email.py                      (sends to HR_EMAIL)
    python scripts/send_test_email.py --to someone@example.com
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import emailer  # noqa: E402


def main():
    args = sys.argv[1:]
    to = args[args.index("--to") + 1] if "--to" in args else emailer.hr_email_address()
    print(f"Sending a test email to {to} ...")
    ok = emailer.send_email(
        to,
        "Test email from the HR Policy Assistant",
        "If you can read this, your email settings work.",
    )
    print("Sent. Check the inbox (and the spam folder)." if ok else "Not sent. See the warning above.")


if __name__ == "__main__":
    main()
