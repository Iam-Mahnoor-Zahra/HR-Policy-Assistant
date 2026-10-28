"""Find exactly which step of sending email fails. It never prints your password.

From the project root:   python scripts/check_smtp.py
"""
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


from dotenv import dotenv_values, load_dotenv

load_dotenv()

NAMES = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "HR_EMAIL")
host = os.getenv("SMTP_HOST", "smtp.gmail.com")
port = int(os.getenv("SMTP_PORT", "587") or "587")
user = os.getenv("SMTP_USER", "")
password = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
to = os.getenv("HR_EMAIL", user)

print(f"Python {sys.version.split()[0]}, {ssl.OPENSSL_VERSION}")
print(f"Host: {host}   Port: {port}")
print(f"User: {user!r}")
print(f"Password length: {len(password)} (a Gmail app password has 16 characters)")
print(f"Send to: {to!r}")

# Values set in this terminal session win over the .env file. Show any mismatch.
file_values = dotenv_values()
for name in NAMES:
    if name in os.environ and name in file_values and os.environ[name] != file_values[name]:
        print(f"[warning] {name} in this terminal session is different from the one in .env")
    elif name in os.environ and name not in file_values:
        print(f"[warning] {name} is set in this terminal session but is not in .env")
print()


def step(name, action):
    try:
        result = action()
        print(f"[ok]     {name}")
        return result
    except Exception as e:
        print(f"[FAILED] {name}: {type(e).__name__}: {e}")
        sys.exit(1)


if port == 465:
    server = step("connect (SSL)", lambda: smtplib.SMTP_SSL(host, port, timeout=20))
    step("hello", server.ehlo)
else:
    server = step("connect", lambda: smtplib.SMTP(host, port, timeout=20))
    step("hello", server.ehlo)
    step("start TLS", server.starttls)
    step("hello again", server.ehlo)

step("login", lambda: server.login(user, password))

msg = EmailMessage()
msg["From"] = user
msg["To"] = to
msg["Subject"] = "SMTP check"
msg.set_content("If you can read this, sending works.")
step("send a test message", lambda: server.send_message(msg))
server.quit()
print("\nAll steps worked. Your email settings are fine.")