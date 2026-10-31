"""Build and send the approval email for urgent open tickets.

The email is multipart/alternative: an HTML part with an Approve and a
Reject button per ticket, and a plain-text fallback with the same links.
Each link opens a confirmation page (see app.approval_links). The result
email sent after a decision is built here too. Standard library only.
"""

import html
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Dict, List, Optional

from app.ticket_summary import parse_timestamp

EMAIL_TIME_FORMAT = "%d/%m/%Y %H:%M"
DATE_FORMAT = "%d/%m/%Y"
EMPTY_VALUE = "—"

# Export fields copied into each ticket line (everything but customer_email).
FIELDS_PER_TICKET = 8

INSTRUCTION = (
    "Click Approve or Reject for each ticket. Each button opens a page where you "
    "confirm your choice. Replies to this email are not recorded."
)

DECISION_VERBS = {"Accept": "approved", "Reject": "rejected"}


def format_created(created_at: str) -> str:
    try:
        parsed = parse_timestamp(created_at)
    except ValueError:
        return created_at or EMPTY_VALUE
    return parsed.strftime(EMAIL_TIME_FORMAT) if parsed else EMPTY_VALUE


def format_refund(amount: Optional[float]) -> str:
    return f"{amount:.2f}" if amount is not None else EMPTY_VALUE


def format_date(value: Optional[datetime]) -> str:
    return value.strftime(DATE_FORMAT) if value else EMPTY_VALUE


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


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


def reminder_line(ticket: Dict) -> Optional[str]:
    """'Reminder: first sent DD/MM/YYYY, waiting N days', or None for a new ticket."""
    if ticket.get("send_reason") != "reminder":
        return None
    first = ticket.get("first_requested_at")
    try:
        first_sent = format_date(parse_timestamp(first)) if first else EMPTY_VALUE
    except ValueError:
        first_sent = EMPTY_VALUE
    days = ticket.get("days_waiting")
    waiting = plural(days, "day") if days is not None else "unknown time"
    return f"Reminder: first sent {first_sent}, waiting {waiting}"


def approval_subject(tickets: List[Dict]) -> str:
    reminders = sum(t.get("send_reason") == "reminder" for t in tickets)
    if reminders:
        return (
            "Urgent tickets awaiting your approval "
            f"({len(tickets)}, including {plural(reminders, 'reminder')})"
        )
    return f"Urgent tickets awaiting your approval ({len(tickets)})"


def _button(url: str, label: str, colour: str) -> str:
    # Email-safe: a table cell with inline CSS, no scripts or stylesheets.
    return (
        f'<td style="background-color:{colour};border-radius:4px;">'
        f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;'
        "padding:10px 22px;font-family:Arial,Helvetica,sans-serif;font-size:15px;"
        f'font-weight:bold;color:#ffffff;text-decoration:none;">{label}</a></td>'
    )


def _html_ticket(ticket: Dict, links: Dict[str, str]) -> str:
    reminder = reminder_line(ticket)
    reminder_html = (
        f'<p style="margin:6px 0 0;color:#92400e;font-size:14px;">{html.escape(reminder)}</p>'
        if reminder
        else ""
    )
    return (
        '<div style="border:1px solid #d0d7de;border-radius:6px;padding:12px;'
        'margin:0 0 14px;">'
        '<p style="margin:0;font-family:Consolas,Menlo,monospace;font-size:14px;'
        f'word-break:break-word;">{html.escape(ticket_line(ticket))}</p>'
        f"{reminder_html}"
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        'style="margin-top:10px;"><tr>'
        f"{_button(links['Accept'], 'Approve', '#15803d')}"
        '<td style="width:12px;"></td>'
        f"{_button(links['Reject'], 'Reject', '#b91c1c')}"
        "</tr></table></div>"
    )


def build_approval_email(
    tickets: List[Dict],
    user_name: str,
    manager_name: str,
    links: Dict[str, Dict[str, str]],
    links_until: datetime,
) -> Dict:
    """Text and HTML bodies with Approve/Reject links for each ticket.

    `links` maps each ticket ID to {"Accept": url, "Reject": url}.
    """
    footer = (
        f"Links work until {format_date(links_until)}. "
        f"Sent by {user_name} from the Escalation Dashboard."
    )

    text = [f"Hi {manager_name},", "", INSTRUCTION, ""]
    for ticket in tickets:
        ticket_links = links[ticket["ticket_id"]]
        text.append(ticket_line(ticket))
        reminder = reminder_line(ticket)
        if reminder:
            text.append(reminder)
        text.extend(
            [f"Approve: {ticket_links['Accept']}", f"Reject: {ticket_links['Reject']}", ""]
        )
    text.append(footer)
    text_body = "\n".join(text) + "\n"

    blocks = "".join(_html_ticket(t, links[t["ticket_id"]]) for t in tickets)
    html_body = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;padding:16px;font-family:Arial,Helvetica,sans-serif;'
        'font-size:15px;color:#1f2328;"><div style="max-width:640px;">'
        f'<p style="margin:0 0 12px;">Hi {html.escape(manager_name)},</p>'
        f'<p style="margin:0 0 16px;">{html.escape(INSTRUCTION)}</p>'
        f"{blocks}"
        f'<p style="margin:16px 0 0;color:#59636e;font-size:13px;">{html.escape(footer)}</p>'
        "</div></body></html>"
    )

    return {
        "subject": approval_subject(tickets),
        # `body` is kept for older clients; it is the plain-text body.
        "body": text_body,
        "text_body": text_body,
        "html_body": html_body,
        "ticket_ids": [ticket["ticket_id"] for ticket in tickets],
    }


def build_result_email(
    ticket: Dict, decision: str, manager_name: str, decided_at: datetime
) -> Dict:
    """The short email sent after the manager confirms a decision."""
    verb = DECISION_VERBS[decision]
    sentence = (
        f"{manager_name} {verb} {ticket['ticket_id']} on "
        f"{decided_at.strftime(DATE_FORMAT)} at {decided_at.strftime('%H:%M')}."
    )
    line = ticket_line(ticket)
    return {
        "subject": f"{ticket['ticket_id']} {verb} by {manager_name}",
        "text_body": f"{sentence}\n\n{line}\n",
        "html_body": (
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            '<body style="font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            f'color:#1f2328;"><p>{html.escape(sentence)}</p>'
            '<p style="font-family:Consolas,Menlo,monospace;font-size:14px;">'
            f"{html.escape(line)}</p></body></html>"
        ),
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


def _with_bodies(message: EmailMessage, email: Dict) -> EmailMessage:
    # set_content then add_alternative gives multipart/alternative.
    message.set_content(email["text_body"])
    message.add_alternative(email["html_body"], subtype="html")
    return message


def build_message(
    email: Dict,
    user_name: str,
    user_email: str,
    manager_name: str,
    manager_email: str,
) -> EmailMessage:
    """The approval email, from the user to the manager."""
    message = EmailMessage()
    message["Subject"] = email["subject"]
    message["From"] = formataddr((user_name, user_email))
    message["To"] = formataddr((manager_name, manager_email))
    message["Reply-To"] = user_email
    return _with_bodies(message, email)


def build_result_message(
    email: Dict,
    user_name: str,
    user_email: str,
    manager_name: str,
    manager_email: str,
) -> EmailMessage:
    """The result email: from the user, to the user, with the manager in Cc."""
    message = EmailMessage()
    message["Subject"] = email["subject"]
    message["From"] = formataddr((user_name, user_email))
    message["To"] = formataddr((user_name, user_email))
    message["Cc"] = formataddr((manager_name, manager_email))
    return _with_bodies(message, email)
