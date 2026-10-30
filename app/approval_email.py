"""Build and send the approval email for urgent open tickets.

The email is plain text, one line per ticket followed by "Decision:", so
the manager can answer inline and the reply can be read back by
app.approval_reply.parse_reply(). Sending uses the standard library only.
"""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Dict, List, Optional

from app.ticket_summary import parse_timestamp

EMAIL_TIME_FORMAT = "%d/%m/%Y %H:%M"
EMPTY_VALUE = "—"

# Export fields copied into each ticket line (everything but customer_email).
FIELDS_PER_TICKET = 8


def format_created(created_at: str) -> str:
    try:
        parsed = parse_timestamp(created_at)
    except ValueError:
        return created_at or EMPTY_VALUE
    return parsed.strftime(EMAIL_TIME_FORMAT) if parsed else EMPTY_VALUE


def format_refund(amount: Optional[float]) -> str:
    return f"{amount:.2f}" if amount is not None else EMPTY_VALUE


def ticket_line(ticket: Dict) -> str:
    """One-line summary used in the email and on the dashboard."""
    labels = ", ".join(ticket["labels"]) or EMPTY_VALUE
    return " | ".join(
        [
            ticket["ticket_id"],
            ticket["category"] or EMPTY_VALUE,
            ticket["priority"] or EMPTY_VALUE,
            f"created {format_created(ticket['created_at'])}",
            ticket["status"] or EMPTY_VALUE,
            f"assigned to {ticket['assigned_to'] or EMPTY_VALUE}",
            f"labels {labels}",
            f"refund {format_refund(ticket['refund_amount'])}",
        ]
    )


def build_approval_email(tickets: List[Dict], user_name: str, manager_name: str) -> Dict:
    subject = f"Urgent tickets awaiting your approval ({len(tickets)})"
    parts = [
        f"Hi {manager_name},",
        "",
        'Please write APPROVE or REJECT after "Decision:" for each ticket below, '
        "then reply to this email.",
        "",
    ]
    for ticket in tickets:
        parts.extend([ticket_line(ticket), "Decision:", ""])
    parts.append(f"Sent by {user_name} from the Escalation Dashboard.")
    return {
        "subject": subject,
        "body": "\n".join(parts) + "\n",
        "ticket_ids": [ticket["ticket_id"] for ticket in tickets],
    }


@dataclass(frozen=True)
class SmtpSettings:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True

    def missing_setting(self) -> Optional[str]:
        # Username and password are optional: local test servers need none.
        if not self.host:
            return "SMTP_HOST"
        if self.username and not self.password:
            return "SMTP_PASSWORD"
        return None


class SmtpEmailSender:
    """Sends one message over SMTP. Tests replace this with a fake."""

    def __init__(self, settings: SmtpSettings):
        self.settings = settings

    def missing_setting(self) -> Optional[str]:
        return self.settings.missing_setting()

    def send(self, message: EmailMessage) -> None:
        s = self.settings
        context = ssl.create_default_context()
        if s.port == 465:
            server = smtplib.SMTP_SSL(s.host, s.port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(s.host, s.port, timeout=30)
        with server:
            if s.use_tls and s.port != 465:
                server.starttls(context=context)
            if s.username:
                server.login(s.username, s.password)
            server.send_message(message)


def build_message(
    email: Dict,
    user_name: str,
    user_email: str,
    manager_name: str,
    manager_email: str,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = email["subject"]
    message["From"] = formataddr((user_name, user_email))
    message["To"] = formataddr((manager_name, manager_email))
    message["Reply-To"] = user_email
    message.set_content(email["body"])
    return message
