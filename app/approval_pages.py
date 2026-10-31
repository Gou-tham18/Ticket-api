"""HTML pages the manager sees after clicking Approve or Reject in the email.

Built in Python with inline CSS and no JavaScript, so they work in any phone
browser. Every value is escaped. Pages never show the token, the secret,
email addresses or file paths.
"""

import html
from datetime import datetime
from typing import Dict, Optional

from app.approval_email import (
    DECISION_VERBS,
    EMAIL_TIME_FORMAT,
    EMPTY_VALUE,
    format_created,
    format_refund,
)
from app.ticket_summary import parse_timestamp

# Sent with every response from /approvals/respond.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}

_STYLE = (
    "body{margin:0;padding:16px;background:#f6f8fa;color:#1f2328;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;"
    "font-size:16px;line-height:1.5}"
    "main{max-width:32rem;margin:0 auto;background:#fff;border:1px solid #d0d7de;"
    "border-radius:8px;padding:20px}"
    "h1{font-size:1.4rem;margin:0 0 12px}"
    "dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0 0 16px}"
    "dt{font-weight:600;color:#59636e}dd{margin:0;overflow-wrap:anywhere}"
    "button{display:block;width:100%;padding:14px;font-size:1.1rem;font-weight:700;"
    "color:#fff;border:0;border-radius:6px;cursor:pointer}"
    ".approve{background:#15803d}.reject{background:#b91c1c}"
    ".note{color:#59636e;font-size:0.95rem}"
    ".warn{background:#fff8c5;border:1px solid #d4a72c;border-radius:6px;padding:8px 12px}"
)


def _page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def _message_page(title: str, *sentences: str) -> str:
    paragraphs = "".join(f"<p>{html.escape(s)}</p>" for s in sentences)
    return _page(title, f"<h1>{html.escape(title)}</h1>{paragraphs}")


def _when(value: Optional[str]) -> Optional[str]:
    """'2026-10-30 10:39' -> '30/10/2026 10:39'."""
    try:
        parsed = parse_timestamp(value) if value else None
    except ValueError:
        return value
    return parsed.strftime(EMAIL_TIME_FORMAT) if parsed else None


def decided_sentence(ticket_id: str, decision: str, decided_by, decided_at) -> str:
    sentence = f"{ticket_id} was already {DECISION_VERBS[decision]}"
    if decided_by:
        sentence += f" by {decided_by}"
    when = _when(decided_at)
    if when:
        sentence += f" on {when}"
    return sentence + "."


def not_configured_page() -> str:
    return _message_page(
        "Approval links unavailable", "Approval links are not set up on the server."
    )


def invalid_page() -> str:
    return _message_page(
        "Link not valid",
        "This link is not valid. Please use the buttons in the latest approval email.",
    )


def expired_page() -> str:
    return _message_page(
        "Link expired",
        "This link has expired. The ticket will be sent to you again as a reminder.",
    )


def already_decided_page(ticket_id: str, escalation: Dict) -> str:
    return _message_page(
        "Already decided",
        decided_sentence(
            ticket_id,
            escalation["decision"],
            escalation["decided_by"],
            escalation["decided_at"],
        ),
        "Nothing was changed. You can close this page.",
    )


def no_decision_needed_page(ticket_id: str, reason: str) -> str:
    return _message_page("No decision needed", f"{ticket_id} {reason}", "You can close this page.")


def unavailable_page() -> str:
    return _message_page(
        "Please try again later",
        "The approval service cannot read its data right now, so nothing was recorded. "
        "Please try the link again in a few minutes.",
    )


def not_saved_page() -> str:
    return _message_page(
        "Decision not saved",
        "Your decision could not be saved on the server, so nothing was recorded. "
        "Please try the link again in a few minutes.",
    )


def error_page() -> str:
    return _message_page(
        "Something went wrong",
        "Something went wrong on the server and nothing was recorded. "
        "Please try the link again in a few minutes.",
    )


def _summary(ticket: Dict) -> str:
    labels = ", ".join(ticket["labels"]) or EMPTY_VALUE
    rows = [
        ("Ticket", ticket["ticket_id"]),
        ("Category", ticket["category"] or EMPTY_VALUE),
        ("Priority", ticket["priority"] or EMPTY_VALUE),
        ("Created", format_created(ticket["created_at"])),
        ("Status", ticket["status"] or EMPTY_VALUE),
        ("Assigned to", ticket["assigned_to"] or EMPTY_VALUE),
        ("Labels", labels),
        ("Refund", format_refund(ticket["refund_amount"])),
    ]
    items = "".join(
        f"<dt>{html.escape(name)}</dt><dd>{html.escape(str(value))}</dd>"
        for name, value in rows
    )
    return f"<dl>{items}</dl>"


def confirm_page(ticket: Dict, decision: str, form_action: str) -> str:
    """Asks the manager to confirm. The form posts back with no fields."""
    verb = "Approve" if decision == "Accept" else "Reject"
    title = f"{verb} {ticket['ticket_id']}?"
    body = (
        f"<h1>{html.escape(title)}</h1>"
        f"{_summary(ticket)}"
        f'<form method="post" action="{html.escape(form_action, quote=True)}">'
        f'<button type="submit" class="{verb.lower()}">Confirm</button></form>'
        '<p class="note">Cancel: close this page to do nothing.</p>'
    )
    return _page(title, body)


def recorded_page(
    ticket_id: str,
    decision: str,
    manager_name: str,
    decided_at: datetime,
    email_sent: bool,
) -> str:
    sentence = (
        f"Recorded: {ticket_id} {DECISION_VERBS[decision]} by {manager_name} "
        f"on {decided_at.strftime(EMAIL_TIME_FORMAT)}. You can close this page."
    )
    body = f"<h1>Decision recorded</h1><p>{html.escape(sentence)}</p>"
    if not email_sent:
        body += (
            '<p class="warn">Your decision is saved, but the confirmation email '
            "could not be sent.</p>"
        )
    return _page("Decision recorded", body)
