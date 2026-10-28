
import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.escalations import (
    AlreadyDecided,
    AlreadyRequested,
    EscalationService,
    NotAnEscalation,
    TicketNotFound,
    UnknownManager,
)
from app.ticket_summary import process_tickets_file
from app.triage_service import (
    GeminiConfigurationError,
    TriageRequest,
    triage_ticket,
)


# Project paths and environment configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ticket data path
DATA_PATH = os.environ.get(
    "TICKETS_DATA_PATH",
    str(PROJECT_ROOT / "data" / "tickets_sample.csv"),
)

WEB_DIR = PROJECT_ROOT / "web"

app = FastAPI(title="ticket-api")


# CORS configuration for the frontend
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://192.168.1.11:5173",  # Added frontend origin
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "https://ticket-api-kr58.onrender.com",
]

# Also allow the dev servers when opened through this machine's network
# address (Vite prints it as "Network"). The LAN IP can change, so match
# any private IPv4 address on the dev ports instead of listing one.
ALLOWED_ORIGIN_REGEX = (
    r"http://("
    r"192\.168\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"):(5173|4173|3000)"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_tickets(path):
    fmt = "%Y-%m-%d %H:%M"
    tickets = []

    with open(path, newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            row["created"] = datetime.strptime(row["created_at"], fmt)
            row["resolved"] = (
                datetime.strptime(row["resolved_at"], fmt)
                if row["resolved_at"]
                else None
            )
            tickets.append(row)

    return tickets


TICKETS = load_tickets(DATA_PATH)


def public(ticket):
    return {
        key: ticket[key]
        for key in (
            "ticket_id",
            "created_at",
            "resolved_at",
            "category",
            "priority",
            "status",
        )
    }


# Existing Task 3 endpoints
@app.get("/tickets")
def list_tickets(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
):
    start = (page - 1) * size
    return [
        public(ticket)
        for ticket in TICKETS[start : start + size]
    ]


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    for ticket in TICKETS:
        if ticket["ticket_id"] == ticket_id:
            return public(ticket)

    raise HTTPException(
        status_code=404,
        detail="ticket not found",
    )


@app.get("/summary")
def summary():
    by_category, average_hours = process_tickets_file(DATA_PATH)

    return {
        "total": sum(by_category.values()),
        "by_category": by_category,
        "average_resolution_hours": average_hours,
    }


# Task 4: AI ticket triage endpoint
@app.post("/triage")
def triage(request: TriageRequest):
    try:
        result = triage_ticket(
            request.subject.strip(),
            request.text.strip(),
        )
        return result.model_dump()

    except GeminiConfigurationError as exc:
        # The message names the missing setting and contains no secrets.
        logger.error("Ticket triage is not configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Ticket triage is not configured: {exc}",
        ) from None

    except Exception as exc:
        # Print the exception type and message for easy diagnosis.
        # The full traceback is also written to the backend log.
        logger.exception("Ticket triage failed")
        print(
            f"TRIAGE ERROR: {type(exc).__name__}: {exc}",
            flush=True,
        )

        # Keep internal exception details out of the HTTP response.
        raise HTTPException(
            status_code=502,
            detail="Ticket triage service failed.",
        ) from None


# Task 5: Help Desk export + escalation tracker
#
# These endpoints read the Help Desk export and the escalation tracker
# that the team already produces. They do not change the existing
# /tickets and /summary endpoints, which keep using TICKETS_DATA_PATH.

HELPDESK_EXPORT_PATH = os.environ.get(
    "HELPDESK_EXPORT_PATH",
    str(PROJECT_ROOT / "data" / "helpdesk_export_sample.csv"),
)
ESCALATION_TRACKER_PATH = os.environ.get(
    "ESCALATION_TRACKER_PATH",
    str(PROJECT_ROOT / "data" / "escalation_tracker_sample.csv"),
)
DECISION_LOG_PATH = os.environ.get(
    "DECISION_LOG_PATH",
    str(PROJECT_ROOT / "data" / "decision_log.csv"),
)

APPROVAL_REQUEST_LOG_PATH = os.environ.get(
    "APPROVAL_REQUEST_LOG_PATH",
    str(PROJECT_ROOT / "data" / "approval_requests.csv"),
)
# Optional comma-separated list. If unset, managers are the approvers
# already named in the escalation tracker.
MANAGERS = [m for m in os.environ.get("MANAGERS", "").split(",") if m.strip()]

_escalation_service: Optional[EscalationService] = None


def get_escalation_service() -> EscalationService:
    global _escalation_service
    if _escalation_service is None:
        _escalation_service = EscalationService(
            HELPDESK_EXPORT_PATH,
            ESCALATION_TRACKER_PATH,
            DECISION_LOG_PATH,
            request_log_path=APPROVAL_REQUEST_LOG_PATH,
            managers=MANAGERS or None,
        )
    return _escalation_service


class DecisionRequest(BaseModel):
    decision: Literal["Accept", "Reject"]
    decided_by: str = Field(..., min_length=1, max_length=100)


class ApprovalRequest(BaseModel):
    requested_by: str = Field(..., min_length=1, max_length=100)
    approver: str = Field(..., min_length=1, max_length=100)


@app.get("/approvals/urgent-open")
def urgent_open_approvals(
    category: Optional[str] = None,
    status: Optional[Literal["open", "in_progress"]] = None,
    service: EscalationService = Depends(get_escalation_service),
):
    """Urgent tickets still open, grouped by where they are in approval."""
    return service.urgent_open_analysis(category=category, status=status)


@app.post("/approvals/{ticket_id}/request")
def request_manager_approval(
    ticket_id: str,
    request: ApprovalRequest,
    service: EscalationService = Depends(get_escalation_service),
):
    try:
        return service.request_approval(
            ticket_id, request.requested_by, request.approver
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except UnknownManager:
        raise HTTPException(
            status_code=422,
            detail=f"approver must be one of: {', '.join(service.managers)}",
        ) from None
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="ticket not found") from None
    except AlreadyRequested:
        raise HTTPException(
            status_code=409,
            detail="approval has already been requested for this ticket",
        ) from None


@app.get("/helpdesk/tickets")
def list_helpdesk_tickets(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    open_only: bool = False,
    escalated: Optional[bool] = None,
    service: EscalationService = Depends(get_escalation_service),
):
    return service.list_tickets(
        status=status,
        category=category,
        priority=priority,
        open_only=open_only,
        escalated=escalated,
    )


@app.get("/helpdesk/tickets/{ticket_id}")
def get_helpdesk_ticket(
    ticket_id: str,
    service: EscalationService = Depends(get_escalation_service),
):
    try:
        return service.ticket_view(ticket_id)
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="ticket not found") from None


@app.get("/escalations")
def list_escalations(
    state: Optional[Literal["pending", "accepted", "rejected"]] = None,
    category: Optional[str] = None,
    open_only: bool = False,
    service: EscalationService = Depends(get_escalation_service),
):
    return service.list_escalations(
        state=state,
        category=category,
        open_only=open_only,
    )


@app.get("/escalations/data-issues")
def escalation_data_issues(
    service: EscalationService = Depends(get_escalation_service),
):
    return service.issues


@app.post("/escalations/{ticket_id}/decision")
def record_escalation_decision(
    ticket_id: str,
    request: DecisionRequest,
    service: EscalationService = Depends(get_escalation_service),
):
    if not request.decided_by.strip():
        raise HTTPException(status_code=422, detail="decided_by must not be blank")
    try:
        return service.record_decision(
            ticket_id, request.decision, request.decided_by
        )
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="ticket not found") from None
    except NotAnEscalation:
        raise HTTPException(
            status_code=409,
            detail="ticket has no escalation tag or tracker row",
        ) from None
    except AlreadyDecided as exc:
        raise HTTPException(
            status_code=409,
            detail=f"escalation already has a final decision: {exc}",
        ) from None


# Preserve the original Task 3 static frontend
app.mount(
    "/",
    StaticFiles(directory=str(WEB_DIR), html=True),
    name="web",
)

