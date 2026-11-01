"""Escalation tracking built on the existing Help Desk export and tracker.

This module reads two files the support team already produces:

- the Help Desk export (one row per ticket), and
- the escalation tracker spreadsheet (one row per approval request).

It joins them by ticket ID, normalises the messy values found in the
tracker (mixed spellings, mixed date formats, duplicate rows), and lets
someone record an Accept or Reject decision against the correct ticket.

The source files are never modified. New decisions are appended to a
separate CSV log that can be opened in the same spreadsheet tool.
"""

import csv
import io
import math
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from app.approval_email import FIELDS_PER_TICKET, ticket_line
from app.approval_reply import ACCEPT, BLANK, REJECT, UNCLEAR, parse_reply
from app.ticket_summary import parse_timestamp


OUTPUT_TIME_FORMAT = "%Y-%m-%d %H:%M"

# Help Desk statuses that mean someone still has to work on the ticket.
OPEN_STATUSES = {"open", "in_progress"}

# Tag spellings seen in the export that mark a ticket as escalated.
ESCALATION_TAGS = {"escalated", "esc"}

# Tracker decision values mapped to the two agreed outcomes.
# Anything not listed here (blank, "Need more info", unknown text)
# is treated as "no final decision yet".
DECISION_ALIASES = {
    "approved": "Accept",
    "ok": "Accept",
    "accept": "Accept",
    "accepted": "Accept",
    "rejected": "Reject",
    "reject": "Reject",
}

# Values that are known and deliberately mean "not decided yet".
KNOWN_PENDING_VALUES = {"", "need more info"}

ALLOWED_DECISIONS = ("Accept", "Reject")

DECISION_LOG_FIELDS = ["ticket_id", "decision", "decided_by", "decided_at"]

REQUEST_LOG_FIELDS = ["ticket_id", "requested_by", "approver", "requested_at"]

# One row per ticket per approval email sent; kind is "new" or "reminder".
EMAIL_LOG_FIELDS = ["ticket_id", "sent_at", "kind"]

DEFAULT_REMINDER_DAYS = 1

RECENT_DECISIONS_LIMIT = 20

URGENT_PRIORITY = "urgent"

# Approval stages used by the urgent-open analysis, in follow-up order.
APPROVAL_STAGES = ("not_requested", "awaiting_decision", "accepted", "rejected")

# Stages whose tickets go in the next approval email.
BATCH_STAGES = ("not_requested", "awaiting_decision")

# Open tickets with a refund above this amount are flagged on the dashboard.
REFUND_THRESHOLD = 200

REPLY_STATUSES = ("accept", "reject", "blank", "unclear", "not_found", "not_awaiting")


class SourceFileError(Exception):
    """The Help Desk export is missing or unusable. The message is safe to show."""


class LogWriteError(Exception):
    """A decision or request log could not be written. Holds the file name."""

    def __init__(self, file_name: str):
        super().__init__(file_name)
        self.file_name = file_name

    def user_message(self) -> str:
        return (
            f"Could not save to {self.file_name}. "
            "Close it if it is open in Excel and try again."
        )


class TicketNotFound(Exception):
    """The ticket ID is not in the Help Desk export."""


class NotAnEscalation(Exception):
    """The ticket exists but has no escalation tag or tracker row."""


class AlreadyDecided(Exception):
    """The escalation already has a final Accept or Reject decision."""


class AlreadyRequested(Exception):
    """Approval has already been requested for this ticket."""


class UnknownManager(Exception):
    """The approver is not one of the known managers."""


def _format_time(value: Optional[datetime]) -> Optional[str]:
    return value.strftime(OUTPUT_TIME_FORMAT) if value else None


def normalise_decision(raw: str) -> Optional[str]:
    """Return "Accept", "Reject", or None for anything that is not final."""
    return DECISION_ALIASES.get(raw.strip().lower())


def is_escalation_tag_set(tags: str) -> bool:
    """True if any semicolon-separated tag is an escalation tag."""
    return any(
        tag.strip().lower() in ESCALATION_TAGS for tag in tags.split(";")
    )


def _raw_labels(row: Dict[str, str]) -> str:
    # The newer export calls the tag column "labels"; older ones use "tags".
    return row.get("labels", row.get("tags", ""))


def label_list(row: Dict[str, str]) -> List[str]:
    """Semicolon-separated labels, lowercased and trimmed, blanks dropped."""
    return [
        label.strip().lower()
        for label in _raw_labels(row).split(";")
        if label.strip()
    ]


def _sort_time(created_at: str) -> datetime:
    try:
        return parse_timestamp(created_at) or datetime.max
    except ValueError:
        return datetime.max


def _reply_counts(results: List[Dict]) -> Dict[str, int]:
    counts = {status: 0 for status in REPLY_STATUSES}
    for result in results:
        counts[result["status"]] += 1
    return counts


def _read_rows(path: Path) -> List[Tuple[Dict[str, str], Optional[str]]]:
    """Rows as clean dicts, each with a problem description or None.

    A short row gets blanks for its missing fields; extra fields on a long
    row are dropped. Either way the row is kept and the problem reported.
    """
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            problem = None
            if None in row:
                problem = "row has more fields than the header; extra fields ignored"
            elif any(value is None for value in row.values()):
                problem = "row has fewer fields than the header; missing fields left blank"
            rows.append(
                (
                    {
                        key.strip(): (value or "").strip()
                        for key, value in row.items()
                        if key is not None
                    },
                    problem,
                )
            )
    return rows


def _read_header(path: Path) -> List[str]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return [column.strip() for column in next(csv.reader(file), [])]


def _append_csv_row(path: Path, fieldnames: List[str], row: Dict[str, str]) -> None:
    """Append one row in a single write, adding the header to a new file.

    Raises LogWriteError (nothing written) if the file cannot be opened,
    for example because it is open in Excel.
    """
    _append_csv_rows(path, fieldnames, [row])


def _is_blank_file(path: Path) -> bool:
    """True if the file is missing or holds only whitespace (no header yet)."""
    if not path.exists():
        return True
    with open(path, "rb") as file:
        return not any(line.strip() for line in file)


def _append_csv_rows(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    """Append several rows in a single write, so none are half-written.

    A file with only blank lines is replaced, so the header is the first
    line; otherwise the reader would take the blank line as the header and
    drop every row.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    try:
        blank = _is_blank_file(path)
        if blank:
            writer.writeheader()
        writer.writerows(rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w" if blank else "a", newline="", encoding="utf-8") as file:
            file.write(buffer.getvalue())
    except OSError as exc:
        raise LogWriteError(path.name) from exc


def check_log_writable(path: Path) -> None:
    """Raise LogWriteError if a later append to this log would fail.

    Opens an existing log for appending without writing anything, which
    fails on Windows while the file is open in Excel. A missing log only
    needs a writable folder; nothing is created.
    """
    try:
        if path.exists():
            with open(path, "a", encoding="utf-8"):
                pass
            return
        folder = path.parent
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        if not os.access(folder, os.W_OK):
            raise PermissionError(folder.name)
    except OSError as exc:
        raise LogWriteError(path.name) from exc


class EscalationService:
    """Joins the Help Desk export with the tracker and records decisions."""

    def __init__(
        self,
        export_path: Path,
        tracker_path: Path,
        decision_log_path: Path,
        clock: Callable[[], datetime] = datetime.now,
        request_log_path: Optional[Path] = None,
        managers: Optional[List[str]] = None,
        fixed_manager: Optional[str] = None,
        email_log_path: Optional[Path] = None,
        reminder_days: int = DEFAULT_REMINDER_DAYS,
    ):
        self.export_path = Path(export_path)
        self.tracker_path = Path(tracker_path)
        self.decision_log_path = Path(decision_log_path)
        self.request_log_path = (
            Path(request_log_path)
            if request_log_path
            else self.decision_log_path.with_name("approval_requests.csv")
        )
        self.email_log_path = (
            Path(email_log_path)
            if email_log_path
            else self.decision_log_path.with_name("approval_emails.csv")
        )
        self.reminder_days = reminder_days
        self.clock = clock
        self.issues: List[Dict[str, str]] = []
        self._lock = threading.Lock()

        self.tickets = self._load_export()
        self.tracker = self._load_tracker()
        # Managers default to the approvers already named in the tracker.
        known_managers = (
            {m.strip() for m in managers if m.strip()}
            if managers
            else {t["approver"] for t in self.tracker.values() if t["approver"]}
        )
        # The manager who receives the approval email must always be accepted.
        if fixed_manager and fixed_manager.strip():
            known_managers.add(fixed_manager.strip())
        self.managers = sorted(known_managers)
        self.refunds = self._load_refunds()
        self._load_request_log()
        self.recorded = self._load_decision_log()
        self.last_emailed = self._load_email_log()

    # Loading -----------------------------------------------------------

    def _issue(self, source: str, ticket_id: str, problem: str) -> None:
        self.issues.append(
            {"source": source, "ticket_id": ticket_id, "problem": problem}
        )

    def _load_export(self) -> Dict[str, Dict[str, str]]:
        name = self.export_path.name
        if not self.export_path.exists():
            raise SourceFileError(
                f"Help Desk export '{name}' was not found. Check HELPDESK_EXPORT_PATH."
            )
        try:
            if "ticket_id" not in _read_header(self.export_path):
                raise SourceFileError(
                    f"Help Desk export '{name}' has no ticket_id column, so tickets "
                    "cannot be read. Check that it is the right file."
                )
            rows = _read_rows(self.export_path)
        except (OSError, UnicodeError, csv.Error):
            raise SourceFileError(
                f"Help Desk export '{name}' could not be read. Check that it is a "
                "UTF-8 CSV file and that it is not open in another program."
            ) from None

        tickets = {}
        for row, problem in rows:
            ticket_id = row.get("ticket_id", "")
            if problem:
                self._issue("helpdesk_export", ticket_id, problem)
            if not ticket_id:
                self._issue("helpdesk_export", "", "row has no ticket_id")
                continue
            if ticket_id in tickets:
                self._issue(
                    "helpdesk_export", ticket_id, "duplicate ticket row ignored"
                )
                continue
            tickets[ticket_id] = row
        return tickets

    def _load_refunds(self) -> Dict[str, Optional[float]]:
        refunds = {}
        for ticket_id, row in self.tickets.items():
            raw = row.get("refund_amount", "")
            try:
                amount = float(raw) if raw else None
                if amount is not None and not math.isfinite(amount):
                    raise ValueError(raw)
                refunds[ticket_id] = amount
            except ValueError:
                self._issue(
                    "helpdesk_export",
                    ticket_id,
                    f"unreadable refund_amount value '{raw}' treated as blank",
                )
                refunds[ticket_id] = None
        return refunds

    def _parse_time(
        self, ticket_id: str, field: str, raw: str, source: str = "escalation_tracker"
    ):
        try:
            return parse_timestamp(raw)
        except ValueError:
            self._issue(source, ticket_id, f"unreadable {field} value '{raw}'")
            return None

    def _read_optional(self, path: Path, source: str) -> List[Tuple[Dict[str, str], Optional[str]]]:
        """Rows of a file the app can work without; problems become data issues."""
        if not path.exists():
            return []
        try:
            return _read_rows(path)
        except (OSError, UnicodeError, csv.Error):
            self._issue(source, "", f"'{path.name}' could not be read; treated as empty")
            return []

    def _load_tracker(self) -> Dict[str, Dict]:
        tracker = {}
        if not self.tracker_path.exists():
            self._issue(
                "escalation_tracker",
                "",
                f"'{self.tracker_path.name}' was not found; working from the export alone",
            )
        for row, problem in self._read_optional(self.tracker_path, "escalation_tracker"):
            ticket_id = row.get("ticket_id", "")
            if problem:
                self._issue("escalation_tracker", ticket_id, problem)

            if ticket_id not in self.tickets:
                self._issue(
                    "escalation_tracker",
                    ticket_id,
                    "ticket is not in the Help Desk export; row ignored",
                )
                continue

            if ticket_id in tracker:
                same = tracker[ticket_id]["_raw"] == row
                self._issue(
                    "escalation_tracker",
                    ticket_id,
                    "exact duplicate row ignored"
                    if same
                    else "conflicting duplicate row ignored; first row kept",
                )
                continue

            raw_decision = row.get("decision", "")
            decision = normalise_decision(raw_decision)
            if (
                decision is None
                and raw_decision.strip().lower() not in KNOWN_PENDING_VALUES
            ):
                self._issue(
                    "escalation_tracker",
                    ticket_id,
                    f"unrecognised decision '{raw_decision}' treated as pending",
                )

            requested_at = self._parse_time(
                ticket_id, "requested_at", row.get("requested_at", "")
            )
            decided_at = self._parse_time(
                ticket_id, "decided_at", row.get("decided_at", "")
            )

            tracker[ticket_id] = {
                "_raw": row,
                "requested_by": row.get("requested_by") or None,
                "approver": row.get("approver") or None,
                "requested_at": requested_at,
                "raw_decision": raw_decision or None,
                "decision": decision,
                # A timestamp only counts once there is a final decision.
                "decided_at": decided_at if decision else None,
                "notes": row.get("notes") or None,
                "request_source": "tracker",
            }
        return tracker

    def _load_request_log(self) -> None:
        """Add approval requests made in the prototype to the tracker view."""
        for row, _ in self._read_optional(self.request_log_path, "approval_request_log"):
            ticket_id = row.get("ticket_id", "")
            if ticket_id not in self.tickets or ticket_id in self.tracker:
                continue
            self.tracker[ticket_id] = self._request_entry(
                row.get("requested_by", ""),
                row.get("approver", ""),
                self._parse_time(
                    ticket_id,
                    "requested_at",
                    row.get("requested_at", ""),
                    source="approval_request_log",
                ),
            )

    @staticmethod
    def _request_entry(requested_by, approver, requested_at) -> Dict:
        return {
            "_raw": None,
            "requested_by": requested_by or None,
            "approver": approver or None,
            "requested_at": requested_at,
            "raw_decision": None,
            "decision": None,
            "decided_at": None,
            "notes": None,
            "request_source": "prototype",
        }

    def _load_decision_log(self) -> Dict[str, Dict]:
        recorded = {}
        for row, _ in self._read_optional(self.decision_log_path, "decision_log"):
            ticket_id = row.get("ticket_id", "")
            if ticket_id in self.tickets and row.get("decision") in ALLOWED_DECISIONS:
                recorded[ticket_id] = {
                    "decision": row["decision"],
                    "decided_by": row.get("decided_by") or None,
                    "decided_at": self._parse_time(
                        ticket_id,
                        "decided_at",
                        row.get("decided_at", ""),
                        source="decision_log",
                    ),
                }
        return recorded

    def _load_email_log(self) -> Dict[str, datetime]:
        """Latest time each ticket was in a sent approval email."""
        last_emailed: Dict[str, datetime] = {}
        for row, _ in self._read_optional(self.email_log_path, "approval_email_log"):
            ticket_id = row.get("ticket_id", "")
            if ticket_id not in self.tickets:
                continue
            sent_at = self._parse_time(
                ticket_id, "sent_at", row.get("sent_at", ""), source="approval_email_log"
            )
            if sent_at and (ticket_id not in last_emailed or sent_at > last_emailed[ticket_id]):
                last_emailed[ticket_id] = sent_at
        return last_emailed

    # Views ---------------------------------------------------------------

    def is_escalated(self, ticket_id: str) -> bool:
        return ticket_id in self.tracker or is_escalation_tag_set(
            _raw_labels(self.tickets[ticket_id])
        )

    def escalation_for(self, ticket_id: str) -> Optional[Dict]:
        """Combined escalation view, or None if the ticket is not escalated."""
        if not self.is_escalated(ticket_id):
            return None

        tracked = self.tracker.get(ticket_id)
        recorded = self.recorded.get(ticket_id)

        if recorded:
            decision = recorded["decision"]
            decided_by = recorded["decided_by"]
            decided_at = recorded["decided_at"]
            decision_source = "prototype"
        elif tracked and tracked["decision"]:
            decision = tracked["decision"]
            # The tracker names an approver but not who actually decided.
            decided_by = tracked["approver"]
            decided_at = tracked["decided_at"]
            decision_source = "tracker"
        else:
            decision = decided_by = decided_at = decision_source = None

        return {
            "in_tracker": tracked is not None,
            "request_source": tracked["request_source"] if tracked else None,
            "requested_by": tracked["requested_by"] if tracked else None,
            "approver": tracked["approver"] if tracked else None,
            "requested_at": _format_time(tracked["requested_at"]) if tracked else None,
            "tracker_decision_raw": tracked["raw_decision"] if tracked else None,
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": _format_time(decided_at),
            "decision_source": decision_source,
            "state": decision.lower() + "ed" if decision else "pending",
            "notes": tracked["notes"] if tracked else None,
        }

    def ticket_view(self, ticket_id: str) -> Dict:
        if ticket_id not in self.tickets:
            raise TicketNotFound(ticket_id)
        row = self.tickets[ticket_id]
        return {
            "ticket_id": ticket_id,
            "category": row.get("category"),
            "priority": row.get("priority"),
            "created_at": row.get("created_at"),
            "status": row.get("status"),
            "is_open": row.get("status", "").lower() in OPEN_STATUSES,
            "assigned_to": row.get("assigned_to") or None,
            "escalation": self.escalation_for(ticket_id),
        }

    def list_tickets(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        open_only: bool = False,
        escalated: Optional[bool] = None,
    ) -> List[Dict]:
        results = []
        for ticket_id in self.tickets:
            view = self.ticket_view(ticket_id)
            if status and view["status"].lower() != status.lower():
                continue
            if category and view["category"].lower() != category.lower():
                continue
            if priority and view["priority"].lower() != priority.lower():
                continue
            if open_only and not view["is_open"]:
                continue
            if escalated is not None and (view["escalation"] is not None) != escalated:
                continue
            results.append(view)
        return results

    def list_escalations(
        self,
        state: Optional[str] = None,
        category: Optional[str] = None,
        open_only: bool = False,
    ) -> List[Dict]:
        return [
            ticket
            for ticket in self.list_tickets(
                category=category, open_only=open_only, escalated=True
            )
            if state is None or ticket["escalation"]["state"] == state
        ]

    @staticmethod
    def approval_stage(view: Dict) -> str:
        escalation = view["escalation"]
        if escalation is None:
            return "not_requested"
        # A final decision wins, even for a tagged ticket that was decided
        # without ever having a tracker row.
        if escalation["state"] in ("accepted", "rejected"):
            return escalation["state"]
        if not escalation["in_tracker"]:
            return "not_requested"
        return "awaiting_decision"

    def _hours_since(self, timestamp: Optional[str]) -> Optional[float]:
        if not timestamp:
            return None
        try:
            then = parse_timestamp(timestamp)
        except ValueError:
            return None
        if then is None:
            return None
        return round((self.clock() - then).total_seconds() / 3600, 1)

    def urgent_open_analysis(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict:
        """Urgent tickets that are still open, grouped by approval stage."""
        tickets = []
        for view in self.list_tickets(
            priority=URGENT_PRIORITY, category=category, status=status, open_only=True
        ):
            stage = self.approval_stage(view)
            escalation = view["escalation"] or {}
            tickets.append(
                {
                    **view,
                    "approval_stage": stage,
                    "age_hours": self._hours_since(view["created_at"]),
                    "waiting_for_decision_hours": (
                        self._hours_since(escalation.get("requested_at"))
                        if stage == "awaiting_decision"
                        else None
                    ),
                }
            )

        # Needs action first (not requested, then awaiting), oldest first.
        tickets.sort(
            key=lambda t: (APPROVAL_STAGES.index(t["approval_stage"]), t["created_at"])
        )

        by_stage = {stage: 0 for stage in APPROVAL_STAGES}
        by_category: Dict[str, int] = {}
        for ticket in tickets:
            by_stage[ticket["approval_stage"]] += 1
            by_category[ticket["category"]] = by_category.get(ticket["category"], 0) + 1

        return {
            "total": len(tickets),
            "needs_action": by_stage["not_requested"] + by_stage["awaiting_decision"],
            "by_stage": by_stage,
            "by_category": by_category,
            "managers": self.managers,
            "tickets": tickets,
        }

    # Dashboard and email approval --------------------------------------------

    def add_manager(self, name: str) -> None:
        name = name.strip()
        with self._lock:
            if name and name not in self.managers:
                self.managers = sorted([*self.managers, name])

    def _dashboard_ticket(self, ticket_id: str) -> Dict:
        view = self.ticket_view(ticket_id)
        row = self.tickets[ticket_id]
        refund = self.refunds.get(ticket_id)
        is_urgent_open = view["is_open"] and view["priority"] == URGENT_PRIORITY

        indicators = []
        if view["is_open"]:
            if is_urgent_open:
                indicators.append("urgent_open")
            if is_escalation_tag_set(_raw_labels(row)):
                indicators.append("escalated_label")
            if refund is not None and refund > REFUND_THRESHOLD:
                indicators.append("refund_over_200")

        escalation = view["escalation"] or {}
        return {
            "ticket_id": ticket_id,
            "category": view["category"],
            "priority": view["priority"],
            "created_at": view["created_at"],
            "status": view["status"],
            "is_open": view["is_open"],
            "assigned_to": view["assigned_to"],
            "labels": label_list(row),
            "refund_amount": refund,
            "indicators": indicators,
            # Urgent open tickets always have a stage (they can be emailed);
            # other tickets only when they are escalated.
            "approval_stage": (
                self.approval_stage(view)
                if is_urgent_open or view["escalation"] is not None
                else None
            ),
            "decision": escalation.get("decision"),
            "decided_by": escalation.get("decided_by"),
            "decided_at": escalation.get("decided_at"),
            "decision_source": escalation.get("decision_source"),
        }

    @staticmethod
    def is_urgent_open(ticket: Dict) -> bool:
        return ticket["is_open"] and ticket["priority"] == URGENT_PRIORITY

    def ticket_summary(self, ticket_id: str) -> Dict:
        """Dashboard fields plus the one-line summary. Raises TicketNotFound."""
        ticket = self._dashboard_ticket(ticket_id)
        ticket["summary_line"] = ticket_line(ticket)
        return ticket

    def _first_requested_at(self, ticket_id: str) -> Optional[datetime]:
        tracked = self.tracker.get(ticket_id)
        if tracked and tracked["requested_at"]:
            return tracked["requested_at"]
        return self.last_emailed.get(ticket_id)

    def last_emailed_at(self, ticket_id: str) -> Optional[datetime]:
        """Latest approval email for the ticket, else when it was requested.

        Tracker requests made before the email log existed count as emailed
        at their requested_at.
        """
        if ticket_id in self.last_emailed:
            return self.last_emailed[ticket_id]
        tracked = self.tracker.get(ticket_id)
        return tracked["requested_at"] if tracked else None

    def _approval_queue(self) -> Tuple[List[Dict], List[Dict]]:
        """(ready to send, waiting for the manager's reply).

        Ready: urgent open tickets never requested ("new"), and those awaiting
        a decision whose last email is at least reminder_days old ("reminder").
        Accepted and rejected tickets never come back.
        """
        now = self.clock()
        wait = timedelta(days=self.reminder_days)
        new, reminders, waiting = [], [], []
        for ticket_id in self.tickets:
            ticket = self._dashboard_ticket(ticket_id)
            if not self.is_urgent_open(ticket) or ticket["approval_stage"] not in BATCH_STAGES:
                continue
            ticket["summary_line"] = ticket_line(ticket)

            if ticket["approval_stage"] == "not_requested":
                new.append(
                    {
                        **ticket,
                        "send_reason": "new",
                        "last_emailed_at": None,
                        "first_requested_at": None,
                        "days_waiting": None,
                    }
                )
                continue

            last = self.last_emailed_at(ticket_id)
            first = self._first_requested_at(ticket_id)
            # An unknown email time (unreadable date) is treated as due now.
            if last is None or now - last >= wait:
                reminders.append(
                    {
                        **ticket,
                        "send_reason": "reminder",
                        "last_emailed_at": _format_time(last),
                        "first_requested_at": _format_time(first),
                        "days_waiting": (now - first).days if first else None,
                    }
                )
            else:
                waiting.append(
                    {
                        "ticket_id": ticket_id,
                        "category": ticket["category"],
                        "summary_line": ticket["summary_line"],
                        "last_emailed_at": _format_time(last),
                        "reminder_due_at": _format_time(last + wait),
                        "_due": last + wait,
                    }
                )

        def oldest_first(t: Dict):
            return (_sort_time(t["created_at"]), t["ticket_id"])

        new.sort(key=oldest_first)
        reminders.sort(key=oldest_first)
        waiting.sort(key=lambda t: (t["_due"], t["ticket_id"]))
        for ticket in waiting:
            del ticket["_due"]
        return new + reminders, waiting

    def approval_batch(self) -> List[Dict]:
        """Tickets ready to send: new first, then reminders, oldest first."""
        return self._approval_queue()[0]

    def waiting_for_reply(self) -> List[Dict]:
        """Emailed tickets not yet due for a reminder, soonest due first."""
        return self._approval_queue()[1]

    def next_reminder_due_at(self) -> Optional[str]:
        waiting = self.waiting_for_reply()
        return waiting[0]["reminder_due_at"] if waiting else None

    def recent_decisions(self) -> List[Dict]:
        """Decisions recorded through the app, newest first, at most 20."""
        # Reversed first so that, for equal times, later log rows come first.
        entries = sorted(
            reversed(list(self.recorded.items())),
            key=lambda item: item[1]["decided_at"] or datetime.min,
            reverse=True,
        )
        return [
            {
                "ticket_id": ticket_id,
                "category": self.tickets[ticket_id].get("category"),
                "decision": entry["decision"],
                "decided_by": entry["decided_by"],
                "decided_at": _format_time(entry["decided_at"]),
            }
            for ticket_id, entry in entries[:RECENT_DECISIONS_LIMIT]
        ]

    def dashboard(self) -> Dict:
        tickets = [self._dashboard_ticket(ticket_id) for ticket_id in self.tickets]
        # Open tickets first, then resolved; oldest first within each group.
        tickets.sort(key=lambda t: (not t["is_open"], _sort_time(t["created_at"])))
        open_tickets = [t for t in tickets if t["is_open"]]
        batch, waiting = self._approval_queue()

        def count(indicator: str) -> int:
            return sum(indicator in t["indicators"] for t in open_tickets)

        return {
            "total_tickets": len(tickets),
            "open_tickets": len(open_tickets),
            "attention": {
                "urgent_open": count("urgent_open"),
                "escalated_label": count("escalated_label"),
                "refund_over_200": count("refund_over_200"),
                "any_condition": sum(bool(t["indicators"]) for t in open_tickets),
            },
            "tickets": tickets,
            "approval_batch": {
                "count": len(batch),
                "fields_saved": len(batch) * FIELDS_PER_TICKET,
                "tickets": batch,
            },
            "reminder_days": self.reminder_days,
            "waiting_for_reply": waiting,
            "next_reminder_due_at": waiting[0]["reminder_due_at"] if waiting else None,
            "recent_decisions": self.recent_decisions(),
        }

    def review_reply(self, reply_text: str) -> Dict:
        """What would be recorded from a pasted reply. Writes nothing."""
        results = []
        for ticket_id, decision in parse_reply(reply_text).items():
            results.append(
                {
                    "ticket_id": ticket_id,
                    # What the parser read: accept, reject, blank, or unclear.
                    "decision": decision,
                    **self._reply_status(ticket_id, decision),
                }
            )
        return {"tickets": results, "counts": _reply_counts(results)}

    def _reply_status(self, ticket_id: str, decision: str) -> Dict:
        if ticket_id not in self.tickets:
            return {"status": "not_found", "reason": "Not in the Help Desk export."}
        stage = self.approval_stage(self.ticket_view(ticket_id))
        if stage != "awaiting_decision":
            reason = (
                f"Already {stage}; the existing decision is kept."
                if stage in ("accepted", "rejected")
                else "Approval was never requested for this ticket."
            )
            return {"status": "not_awaiting", "reason": reason}
        if decision == BLANK:
            return {"status": "blank", "reason": "No decision written; stays awaiting."}
        if decision == UNCLEAR:
            return {
                "status": "unclear",
                "reason": "Both approve and reject words found; not recorded.",
            }
        label = "Accept" if decision == ACCEPT else "Reject"
        return {"status": decision, "reason": f"{label} will be recorded."}

    def record_reply(self, reply_text: str, decided_by: str) -> Dict:
        """Record every clear decision in a pasted reply."""
        review = self.review_reply(reply_text)
        # Fail before recording any decision if the log is locked.
        check_log_writable(self.decision_log_path)
        recorded = []
        for ticket in review["tickets"]:
            if ticket["status"] not in (ACCEPT, REJECT):
                continue
            decision = "Accept" if ticket["status"] == ACCEPT else "Reject"
            try:
                self.record_decision(ticket["ticket_id"], decision, decided_by)
            except (AlreadyDecided, NotAnEscalation):
                # Decided by someone else between the review and now.
                ticket["status"] = "not_awaiting"
                ticket["reason"] = "Decided elsewhere before this reply was recorded."
                continue
            ticket["reason"] = f"{decision} recorded."
            recorded.append(ticket["ticket_id"])
        review["counts"] = _reply_counts(review["tickets"])
        review["recorded"] = recorded
        return review

    def request_approval(self, ticket_id: str, requested_by: str, approver: str) -> Dict:
        requested_by = requested_by.strip()
        if not requested_by:
            raise ValueError("requested_by must not be blank")
        matches = [m for m in self.managers if m.lower() == approver.strip().lower()]
        if not matches:
            raise UnknownManager(approver)
        approver = matches[0]

        with self._lock:
            if ticket_id not in self.tickets:
                raise TicketNotFound(ticket_id)
            if ticket_id in self.tracker:
                raise AlreadyRequested(ticket_id)

            requested_at = self.clock().replace(second=0, microsecond=0)
            # Raises LogWriteError before anything changes in memory.
            _append_csv_row(
                self.request_log_path,
                REQUEST_LOG_FIELDS,
                {
                    "ticket_id": ticket_id,
                    "requested_by": requested_by,
                    "approver": approver,
                    "requested_at": _format_time(requested_at),
                },
            )
            self.tracker[ticket_id] = self._request_entry(
                requested_by, approver, requested_at
            )

        return self.ticket_view(ticket_id)

    def log_emails(self, tickets: List[Dict], sent_at: datetime) -> None:
        """Record that these batch tickets were emailed, in one write.

        Raises LogWriteError before anything changes in memory.
        """
        sent_at = sent_at.replace(second=0, microsecond=0)
        with self._lock:
            _append_csv_rows(
                self.email_log_path,
                EMAIL_LOG_FIELDS,
                [
                    {
                        "ticket_id": ticket["ticket_id"],
                        "sent_at": _format_time(sent_at),
                        "kind": ticket["send_reason"],
                    }
                    for ticket in tickets
                ],
            )
            for ticket in tickets:
                self.last_emailed[ticket["ticket_id"]] = sent_at

    # Recording -----------------------------------------------------------

    def record_decision(self, ticket_id: str, decision: str, decided_by: str) -> Dict:
        if decision not in ALLOWED_DECISIONS:
            raise ValueError("decision must be Accept or Reject")
        decided_by = decided_by.strip()
        if not decided_by:
            raise ValueError("decided_by must not be blank")

        with self._lock:
            if ticket_id not in self.tickets:
                raise TicketNotFound(ticket_id)
            current = self.escalation_for(ticket_id)
            if current is None:
                raise NotAnEscalation(ticket_id)
            if current["decision"] is not None:
                raise AlreadyDecided(current["decision"])

            decided_at = self.clock().replace(second=0, microsecond=0)
            self._append_to_log(ticket_id, decision, decided_by, decided_at)
            self.recorded[ticket_id] = {
                "decision": decision,
                "decided_by": decided_by,
                "decided_at": decided_at,
            }

        return self.ticket_view(ticket_id)

    def _append_to_log(self, ticket_id, decision, decided_by, decided_at):
        # Raises LogWriteError before anything changes in memory.
        _append_csv_row(
            self.decision_log_path,
            DECISION_LOG_FIELDS,
            {
                "ticket_id": ticket_id,
                "decision": decision,
                "decided_by": decided_by,
                "decided_at": _format_time(decided_at),
            },
        )
