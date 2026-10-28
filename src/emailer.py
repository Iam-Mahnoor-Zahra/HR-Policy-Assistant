"""Sending email. One shared function is used for HR notices and employee notices.

Settings come from .env (or the hosting secrets):
    SMTP_HOST (default smtp.gmail.com), SMTP_PORT (default 587),
    SMTP_USER, SMTP_PASSWORD (an app password), EMAIL_FROM_NAME, HR_EMAIL
"""
import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()


def _settings() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", "").replace(" ", ""),  # app passwords are shown with spaces
        "from_name": os.getenv("EMAIL_FROM_NAME", "HR Policy Assistant"),
    }


def hr_email_address() -> str:
    return os.getenv("HR_EMAIL", "hr@examplecorp.com")


def send_email(to: str, subject: str, body: str, reply_to: str | None = None) -> bool:
    """Send a plain-text email. Returns True if it was sent. Never raises an error."""
    s = _settings()
    if not (s["user"] and s["password"]):
        print("[warning] email is not set up (SMTP_USER or SMTP_PASSWORD is missing)")
        return False
    if not to:
        print("[warning] no recipient address, so the email was not sent")
        return False

    msg = EmailMessage()
    msg["From"] = f"{s['from_name']} <{s['user']}>"
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        if s["port"] == 465:
            with smtplib.SMTP_SSL(s["host"], s["port"], timeout=20) as server:
                server.login(s["user"], s["password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP(s["host"], s["port"], timeout=20) as server:
                server.starttls()
                server.login(s["user"], s["password"])
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"[warning] could not send the email: {type(e).__name__}: {e}")
        return False


def email_hr(subject: str, body: str, reply_to: str | None = None) -> bool:
    return send_email(hr_email_address(), subject, body, reply_to=reply_to)


def email_employee(address: str, subject: str, body: str) -> bool:
    return send_email(address, subject, body)
