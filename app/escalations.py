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
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

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

URGENT_PRIORITY = "urgent"

# Approval stages used by the urgent-open analysis, in follow-up order.
APPROVAL_STAGES = ("not_requested", "awaiting_decision", "accepted", "rejected")


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


def _read_rows(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return [
            {key.strip(): (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


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
    ):
        self.export_path = Path(export_path)
        self.tracker_path = Path(tracker_path)
        self.decision_log_path = Path(decision_log_path)
        self.request_log_path = (
            Path(request_log_path)
            if request_log_path
            else self.decision_log_path.with_name("approval_requests.csv")
        )
        self.clock = clock
        self.issues: List[Dict[str, str]] = []
        self._lock = threading.Lock()

        self.tickets = self._load_export()
        self.tracker = self._load_tracker()
        # Managers default to the approvers already named in the tracker.
        self.managers = sorted(
            {m.strip() for m in managers if m.strip()}
            if managers
            else {t["approver"] for t in self.tracker.values() if t["approver"]}
        )
        self._load_request_log()
        self.recorded = self._load_decision_log()

    # Loading -----------------------------------------------------------

    def _issue(self, source: str, ticket_id: str, problem: str) -> None:
        self.issues.append(
            {"source": source, "ticket_id": ticket_id, "problem": problem}
        )

    def _load_export(self) -> Dict[str, Dict[str, str]]:
        tickets = {}
        for row in _read_rows(self.export_path):
            ticket_id = row.get("ticket_id", "")
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

    def _parse_tracker_time(self, ticket_id: str, field: str, raw: str):
        try:
            return parse_timestamp(raw)
        except ValueError:
            self._issue(
                "escalation_tracker",
                ticket_id,
                f"unreadable {field} value '{raw}'",
            )
            return None

    def _load_tracker(self) -> Dict[str, Dict]:
        tracker = {}
        for row in _read_rows(self.tracker_path):
            ticket_id = row.get("ticket_id", "")

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

            requested_at = self._parse_tracker_time(
                ticket_id, "requested_at", row.get("requested_at", "")
            )
            decided_at = self._parse_tracker_time(
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
        if not self.request_log_path.exists():
            return
        for row in _read_rows(self.request_log_path):
            ticket_id = row.get("ticket_id", "")
            if ticket_id not in self.tickets or ticket_id in self.tracker:
                continue
            self.tracker[ticket_id] = self._request_entry(
                row.get("requested_by", ""),
                row.get("approver", ""),
                parse_timestamp(row.get("requested_at", "")),
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
        if not self.decision_log_path.exists():
            return recorded
        for row in _read_rows(self.decision_log_path):
            ticket_id = row.get("ticket_id", "")
            if ticket_id in self.tickets and row.get("decision") in ALLOWED_DECISIONS:
                recorded[ticket_id] = {
                    "decision": row["decision"],
                    "decided_by": row.get("decided_by") or None,
                    "decided_at": parse_timestamp(row.get("decided_at", "")),
                }
        return recorded

    # Views ---------------------------------------------------------------

    def is_escalated(self, ticket_id: str) -> bool:
        ticket = self.tickets[ticket_id]
        return ticket_id in self.tracker or is_escalation_tag_set(
            ticket.get("tags", "")
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
        if escalation is None or not escalation["in_tracker"]:
            return "not_requested"
        if escalation["state"] == "pending":
            return "awaiting_decision"
        return escalation["state"]

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
            self.request_log_path.parent.mkdir(parents=True, exist_ok=True)
            new_file = not self.request_log_path.exists()
            with open(self.request_log_path, "a", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=REQUEST_LOG_FIELDS)
                if new_file:
                    writer.writeheader()
                writer.writerow(
                    {
                        "ticket_id": ticket_id,
                        "requested_by": requested_by,
                        "approver": approver,
                        "requested_at": _format_time(requested_at),
                    }
                )
            self.tracker[ticket_id] = self._request_entry(
                requested_by, approver, requested_at
            )

        return self.ticket_view(ticket_id)

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
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.decision_log_path.exists()
        with open(self.decision_log_path, "a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=DECISION_LOG_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "ticket_id": ticket_id,
                    "decision": decision,
                    "decided_by": decided_by,
                    "decided_at": _format_time(decided_at),
                }
            )
