"""
Outbound email. One transactional path exists: password-reset links.

This is deliberately the app's only send mechanism -- outreach pitches are still
copied by the student into their own mail client, and nothing here changes that.

Stdlib SMTP (STARTTLS) rather than a provider SDK: the corpus of reset emails is
tiny, a Gmail app password is enough to launch with, and swapping to SES/Mailgun
later is an .env change, not a dependency change.

Fail-closed: callers must check is_email_configured() and surface an honest 503
when SMTP is unset -- never a "we sent you an email" the app didn't send. That is
the repo's core trust rule applied to ourselves, and it mirrors how jwt_secret
and analytics_admin_secret behave when unconfigured.

send_email() lets exceptions propagate. The route decides what a failure means to
the user; swallowing it here would turn "no email is coming" into silent success.
"""
import smtplib
from email.message import EmailMessage

from ..config import settings

# A dead SMTP host should fail inside the frontend's 30s axios timeout, not pin a
# threadpool worker until the socket gives up on its own.
SMTP_TIMEOUT_SECONDS = 15


def is_email_configured() -> bool:
    """True when SMTP is set up enough to actually deliver mail."""
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email synchronously. Raises on any failure.

    Blocking by design -- call it from a plain `def` route so FastAPI runs it in
    the threadpool instead of stalling the event loop.
    """
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_username
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)
