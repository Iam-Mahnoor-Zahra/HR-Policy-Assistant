import smtplib

from src import emailer


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.logged_in_with = None
        self.sent = []
        self.fail_login = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        if self.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.logged_in_with = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def _configure(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("HR_EMAIL", "hr@example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


def test_not_configured_returns_false(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    assert emailer.send_email("a@b.com", "Hi", "Body") is False


def test_email_is_sent_with_clean_password_and_reply_to(monkeypatch):
    _configure(monkeypatch)
    ok = emailer.email_hr("Subject", "Body", reply_to="sara@example.com")
    server = FakeSMTP.instances[0]
    assert ok is True
    assert server.logged_in_with == ("sender@example.com", "abcdefghijklmnop")  # spaces removed
    msg = server.sent[0]
    assert msg["To"] == "hr@example.com"
    assert msg["Reply-To"] == "sara@example.com"
    assert msg["Subject"] == "Subject"


def test_email_employee_goes_to_the_given_address(monkeypatch):
    _configure(monkeypatch)
    assert emailer.email_employee("sara@example.com", "Hi", "Body") is True
    assert FakeSMTP.instances[0].sent[0]["To"] == "sara@example.com"


def test_a_failed_login_returns_false_and_does_not_raise(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(FakeSMTP, "login", lambda self, u, p: (_ for _ in ()).throw(RuntimeError("down")))
    assert emailer.send_email("a@b.com", "Hi", "Body") is False


def test_missing_recipient_returns_false(monkeypatch):
    _configure(monkeypatch)
    assert emailer.send_email("", "Hi", "Body") is False
