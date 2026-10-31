
import csv
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from typing import Annotated, List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import approval_pages as pages
from app.approval_email import (
    DATE_FORMAT,
    SmtpEmailSender,
    SmtpSettings,
    build_approval_email,
    build_message,
    build_result_email,
    build_result_message,
    plural,
)
from app.approval_links import (
    DECISION_CODES,
    ExpiredLink,
    InvalidLink,
    link_for,
    make_token,
    read_token,
)
from app.approval_reply import NoTicketsInReply
from app.escalations import (
    DEFAULT_REMINDER_DAYS,
    AlreadyDecided,
    AlreadyRequested,
    EscalationService,
    LogWriteError,
    NotAnEscalation,
    SourceFileError,
    TicketNotFound,
    UnknownManager,
    check_log_writable,
)
from app.ticket_summary import parse_timestamp, process_tickets_file
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
    str(PROJECT_ROOT / "data" / "helpdesk_export_sample.csv"),
)

WEB_DIR = PROJECT_ROOT / "web"

app = FastAPI(title="ticket-api")

# The page the manager reaches from the email. Its errors are HTML, never JSON.
RESPOND_PATH = "/approvals/respond"


def _page_response(content: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(content, status_code=status_code, headers=pages.PAGE_HEADERS)

UNEXPECTED_ERROR_MESSAGE = (
    "Something went wrong on the server. Please try again, and if it keeps "
    "happening, report the time and this error ID."
)


async def catch_unexpected_errors(request: Request, call_next):
    """Turn any unhandled exception into a 500 with a short error ID.

    Added before the CORS middleware so CORS wraps it and the browser can
    read the error. HTTPException and the handlers below never reach here.
    """
    try:
        return await call_next(request)
    except Exception:
        error_id = uuid.uuid4().hex[:8]
        logger.exception(
            "Unexpected error %s on %s %s", error_id, request.method, request.url.path
        )
        if request.url.path == RESPOND_PATH:
            return _page_response(pages.error_page(), 500)
        return JSONResponse(
            status_code=500,
            content={"detail": UNEXPECTED_ERROR_MESSAGE, "error_id": error_id},
        )


app.add_middleware(BaseHTTPMiddleware, dispatch=catch_unexpected_errors)


def _field_name(loc) -> str:
    names = [str(part) for part in loc if part not in ("body", "query", "path")]
    names = [name for name in names if not name.isdigit()]
    return names[-1] if names else "request body"


def plain_validation_message(error: dict) -> str:
    """One plain sentence naming the field, for a pydantic/FastAPI error."""
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    loc = tuple(error.get("loc", ()))
    field = _field_name(loc)

    if kind == "plain":
        return error.get("msg", "")
    if kind == "json_invalid":
        return "The request body is not valid JSON."
    if kind in ("model_attributes_type", "dict_type", "model_type"):
        return "The request body must be a JSON object."
    if kind == "missing":
        return "The request body is required." if loc == ("body",) else f"{field} is required."
    if kind == "string_too_long":
        return f"{field} must be {ctx.get('max_length')} characters or fewer."
    if kind == "string_too_short":
        return f"{field} must not be empty."
    if kind == "string_pattern_mismatch":
        if field == "ticket_id":
            return "Ticket IDs look like TCK-5007."
        return f"{field} is not in the expected format."
    if kind == "literal_error":
        expected = str(ctx.get("expected", "")).replace("'", "")
        return f"{field} must be {expected}."
    if kind == "greater_than_equal":
        return f"{field} must be {ctx.get('ge')} or more."
    if kind == "less_than_equal":
        return f"{field} must be {ctx.get('le')} or less."
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return f"{field} must be a whole number."
    if kind in ("bool_parsing", "bool_type"):
        return f"{field} must be true or false."
    if kind == "string_type":
        return f"{field} must be text."
    return f"{field}: {error.get('msg', 'is not valid')}."


@app.exception_handler(RequestValidationError)
def request_validation_error(request: Request, exc: RequestValidationError):
    # Same shape as FastAPI's default (`detail` list with loc and msg), so
    # existing clients keep working, plus `message` with the first problem.
    detail = [
        {
            "loc": list(error.get("loc", ())),
            "msg": plain_validation_message(error),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    message = detail[0]["msg"] if detail else "The request is not valid."
    return JSONResponse(status_code=422, content={"detail": detail, "message": message})


def _require_one_of(field: str, value: Optional[str], allowed: tuple) -> None:
    if value is not None and value.strip().lower() not in allowed:
        raise RequestValidationError(
            [
                {
                    "type": "plain",
                    "loc": ("query", field),
                    "msg": f"{field} must be one of: {', '.join(allowed)}.",
                }
            ]
        )


def not_blank(cls, value: str, info: ValidationInfo) -> str:
    """Field validator: reject empty and whitespace-only names."""
    if not value.strip():
        raise PydanticCustomError("plain", f"{info.field_name} must not be blank.")
    return value


TICKET_ID_PATTERN = r"^TCK-\d{1,10}$"
TicketId = Annotated[str, PathParam(pattern=TICKET_ID_PATTERN)]
CategoryQuery = Query(None, max_length=50)
HELPDESK_STATUSES = ("open", "in_progress", "resolved", "closed")
HELPDESK_PRIORITIES = ("urgent", "high", "normal", "low")


@app.exception_handler(SourceFileError)
def source_file_error(request: Request, exc: SourceFileError):
    if request.url.path == RESPOND_PATH:
        logger.error("Approval page unavailable: %s", exc)
        return _page_response(pages.unavailable_page(), 503)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(LogWriteError)
def log_write_error(request: Request, exc: LogWriteError):
    logger.error("Could not write %s: %s", exc.file_name, exc.__cause__)
    if request.url.path == RESPOND_PATH:
        return _page_response(pages.not_saved_page(), 503)
    return JSONResponse(status_code=503, content={"detail": exc.user_message()})


# CORS configuration for the frontend
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
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
    # Accept the same messy input as process_tickets_file: a UTF-8 BOM,
    # padded values, day-first dates, and blank or malformed rows.
    tickets = []

    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            row = {
                key.strip(): (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            if not row.get("ticket_id"):
                if any(row.values()):
                    logger.warning(
                        "Skipping ticket row at line %d: no ticket_id",
                        reader.line_num,
                    )
                continue
            try:
                row["created"] = parse_timestamp(row.get("created_at", ""))
                row["resolved"] = parse_timestamp(row.get("resolved_at", ""))
            except ValueError as exc:
                logger.warning(
                    "Skipping ticket row at line %d: %s", reader.line_num, exc
                )
                continue
            tickets.append(row)

    return tickets


def public(ticket):
    return {
        key: ticket.get(key, "")
        for key in (
            "ticket_id",
            "created_at",
            "resolved_at",
            "category",
            "priority",
            "status",
        )
    }


def _ticket_file_problem(exc: Exception) -> str:
    name = Path(DATA_PATH).name
    if isinstance(exc, FileNotFoundError):
        return f"Ticket data file '{name}' was not found. Check TICKETS_DATA_PATH."
    return f"Ticket data file '{name}' could not be read. Check TICKETS_DATA_PATH."


def _load_ticket_data():
    """(tickets, None) or (None, problem). Never raises, so the app starts."""
    try:
        return load_tickets(DATA_PATH), None
    except (OSError, UnicodeError, csv.Error) as exc:
        problem = _ticket_file_problem(exc)
        logger.warning("%s /tickets and /summary will return 503.", problem)
        return None, problem


TICKETS, TICKETS_ERROR = _load_ticket_data()


def get_tickets():
    """The Task 3 tickets, retrying the file if it failed to load at startup."""
    global TICKETS, TICKETS_ERROR
    if TICKETS is None:
        TICKETS, TICKETS_ERROR = _load_ticket_data()
    if TICKETS is None:
        raise HTTPException(status_code=503, detail=TICKETS_ERROR)
    return TICKETS


# Existing Task 3 endpoints
@app.get("/tickets")
def list_tickets(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    tickets: list = Depends(get_tickets),
):
    start = (page - 1) * size
    return [
        public(ticket)
        for ticket in tickets[start : start + size]
    ]


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, tickets: list = Depends(get_tickets)):
    for ticket in tickets:
        if ticket["ticket_id"] == ticket_id:
            return public(ticket)

    raise HTTPException(
        status_code=404,
        detail="ticket not found",
    )


@app.get("/summary")
def summary(tickets: list = Depends(get_tickets)):
    try:
        by_category, average_hours = process_tickets_file(DATA_PATH)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise HTTPException(status_code=503, detail=_ticket_file_problem(exc)) from None

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

# Email approval round trip: one fixed team member sends urgent tickets to
# one fixed manager, who answers with the Approve/Reject buttons in the email.
APPROVAL_USER_NAME = os.environ.get("APPROVAL_USER_NAME", "").strip()
APPROVAL_USER_EMAIL = os.environ.get("APPROVAL_USER_EMAIL", "").strip()
APPROVAL_MANAGER_NAME = os.environ.get("APPROVAL_MANAGER_NAME", "").strip()
APPROVAL_MANAGER_EMAIL = os.environ.get("APPROVAL_MANAGER_EMAIL", "").strip()

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = os.environ.get("SMTP_PORT", "587").strip() or "587"
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
# Never returned by the API or written to the log.
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").strip().lower() not in (
    "false", "0", "no",
)

# Approve/Reject buttons in the email.
DEFAULT_LINK_DAYS = 7
MAX_SETTING_DAYS = 30
MIN_LINK_SECRET_LENGTH = 32


def day_setting(name: str, raw: Optional[str], default: int) -> int:
    """A whole number of days from 1 to 30. Anything else falls back to the
    default with a warning; the value itself is not logged."""
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if 1 <= value <= MAX_SETTING_DAYS:
        return value
    logger.warning(
        "%s must be a whole number from 1 to %d; using the default %d.",
        name, MAX_SETTING_DAYS, default,
    )
    return default


def public_base_url_setting(raw: str) -> str:
    """https://... (or http://... for local testing), without a trailing /."""
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    if not value.lower().startswith(("https://", "http://")) or "://" == value[-3:]:
        logger.warning(
            "PUBLIC_BASE_URL must start with https:// (or http:// for local "
            "testing); it is ignored."
        )
        return ""
    if value.lower().startswith("http://"):
        logger.warning("PUBLIC_BASE_URL uses http://. Use https:// outside local testing.")
    return value


def link_secret_setting(raw: str) -> str:
    value = raw.strip()
    if value and len(value) < MIN_LINK_SECRET_LENGTH:
        logger.warning(
            "APPROVAL_LINK_SECRET must be at least %d characters; it is ignored.",
            MIN_LINK_SECRET_LENGTH,
        )
        return ""
    return value


PUBLIC_BASE_URL = public_base_url_setting(os.environ.get("PUBLIC_BASE_URL", ""))
# Never returned by the API, shown on a page, or written to the log.
APPROVAL_LINK_SECRET = link_secret_setting(os.environ.get("APPROVAL_LINK_SECRET", ""))
APPROVAL_LINK_DAYS = day_setting(
    "APPROVAL_LINK_DAYS", os.environ.get("APPROVAL_LINK_DAYS"), DEFAULT_LINK_DAYS
)
APPROVAL_REMINDER_DAYS = day_setting(
    "APPROVAL_REMINDER_DAYS", os.environ.get("APPROVAL_REMINDER_DAYS"), DEFAULT_REMINDER_DAYS
)
APPROVAL_EMAIL_LOG_PATH = os.environ.get(
    "APPROVAL_EMAIL_LOG_PATH",
    str(PROJECT_ROOT / "data" / "approval_emails.csv"),
)

_escalation_service: Optional[EscalationService] = None
_escalation_files_signature = None
_escalation_service_lock = threading.Lock()


def _escalation_files_signature_now():
    """Modification times of the files the service reads (None if missing)."""
    signature = []
    for path in (
        HELPDESK_EXPORT_PATH,
        ESCALATION_TRACKER_PATH,
        DECISION_LOG_PATH,
        APPROVAL_REQUEST_LOG_PATH,
        APPROVAL_EMAIL_LOG_PATH,
    ):
        try:
            signature.append(os.stat(path).st_mtime_ns)
        except FileNotFoundError:
            signature.append(None)
    return tuple(signature)


def get_escalation_service() -> EscalationService:
    # Reload when any source file changes, so a replaced export or an
    # edited tracker is picked up without restarting the backend.
    global _escalation_service, _escalation_files_signature
    with _escalation_service_lock:
        signature = _escalation_files_signature_now()
        if _escalation_service is None or signature != _escalation_files_signature:
            _escalation_service = EscalationService(
                HELPDESK_EXPORT_PATH,
                ESCALATION_TRACKER_PATH,
                DECISION_LOG_PATH,
                request_log_path=APPROVAL_REQUEST_LOG_PATH,
                managers=MANAGERS or None,
                fixed_manager=APPROVAL_MANAGER_NAME or None,
                email_log_path=APPROVAL_EMAIL_LOG_PATH,
                reminder_days=APPROVAL_REMINDER_DAYS,
            )
            _escalation_files_signature = signature
        return _escalation_service


@dataclass(frozen=True)
class ApprovalSettings:
    user_name: str
    user_email: str
    manager_name: str
    manager_email: str
    public_base_url: str = ""
    link_secret: str = field(default="", repr=False)
    link_days: int = DEFAULT_LINK_DAYS

    def missing_name_setting(self) -> Optional[str]:
        if not self.user_name:
            return "APPROVAL_USER_NAME"
        if not self.manager_name:
            return "APPROVAL_MANAGER_NAME"
        return None

    def missing_email_setting(self) -> Optional[str]:
        if not self.user_email:
            return "APPROVAL_USER_EMAIL"
        if not self.manager_email:
            return "APPROVAL_MANAGER_EMAIL"
        return None

    def missing_link_settings(self) -> List[str]:
        """Names of the button settings that are not set, never their values."""
        missing = []
        if not self.public_base_url:
            missing.append("PUBLIC_BASE_URL")
        if not self.link_secret:
            missing.append("APPROVAL_LINK_SECRET")
        return missing


def get_approval_settings() -> ApprovalSettings:
    return ApprovalSettings(
        user_name=APPROVAL_USER_NAME,
        user_email=APPROVAL_USER_EMAIL,
        manager_name=APPROVAL_MANAGER_NAME,
        manager_email=APPROVAL_MANAGER_EMAIL,
        public_base_url=PUBLIC_BASE_URL,
        link_secret=APPROVAL_LINK_SECRET,
        link_days=APPROVAL_LINK_DAYS,
    )


def get_email_sender() -> SmtpEmailSender:
    try:
        port = int(SMTP_PORT)
    except ValueError:
        port = 0  # reported as a missing setting below
    return SmtpEmailSender(
        SmtpSettings(
            host=SMTP_HOST if port else "",
            port=port,
            username=SMTP_USERNAME,
            password=SMTP_PASSWORD,
            use_tls=SMTP_USE_TLS,
        )
    )


def _not_configured(setting: str) -> HTTPException:
    # Same style as the GEMINI_API_KEY message from /triage.
    return HTTPException(
        status_code=503,
        detail=(
            f"Email approval is not configured: {setting} is not set. "
            "Add it to the backend .env file, then restart the backend."
        ),
    )


def require_approval_names(
    settings: ApprovalSettings = Depends(get_approval_settings),
) -> ApprovalSettings:
    missing = settings.missing_name_setting()
    if missing:
        raise _not_configured(missing)
    return settings


class ReplyRequest(BaseModel):
    reply_text: str = Field(..., max_length=50_000)

    @field_validator("reply_text")
    @classmethod
    def reply_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("plain", "Paste the manager's reply before checking it.")
        return value


class DecisionRequest(BaseModel):
    decision: Literal["Accept", "Reject"]
    decided_by: str = Field(..., max_length=100)

    _not_blank = field_validator("decided_by")(not_blank)


class ApprovalRequest(BaseModel):
    requested_by: str = Field(..., max_length=100)
    approver: str = Field(..., max_length=100)

    _not_blank = field_validator("requested_by", "approver")(not_blank)


@app.get("/approvals/urgent-open")
def urgent_open_approvals(
    category: Optional[str] = CategoryQuery,
    status: Optional[Literal["open", "in_progress"]] = None,
    service: EscalationService = Depends(get_escalation_service),
):
    """Urgent tickets still open, grouped by where they are in approval."""
    return service.urgent_open_analysis(category=category, status=status)


@app.get("/approvals/config")
def approval_config(
    settings: ApprovalSettings = Depends(get_approval_settings),
    sender: SmtpEmailSender = Depends(get_email_sender),
):
    """Who sends and who approves. No addresses, SMTP details or link values."""
    buttons_missing = settings.missing_link_settings()
    return {
        "user_name": settings.user_name or None,
        "manager_name": settings.manager_name or None,
        "configured": settings.missing_name_setting() is None,
        "email_configured": (
            settings.missing_name_setting() is None
            and settings.missing_email_setting() is None
            and sender.missing_setting() is None
            and not buttons_missing
        ),
        "buttons_configured": not buttons_missing,
        # Setting names only, so the dashboard can say what to add.
        "buttons_missing": buttons_missing,
    }


@app.get("/dashboard")
def dashboard(
    service: EscalationService = Depends(get_escalation_service),
    settings: ApprovalSettings = Depends(get_approval_settings),
):
    return {**service.dashboard(), "link_days": settings.link_days}


def require_link_settings(settings: ApprovalSettings) -> None:
    missing = settings.missing_link_settings()
    if missing:
        raise _not_configured(missing[0])


def _batch_email(settings: ApprovalSettings, batch: list, sent_at: datetime) -> dict:
    """The approval email with a signed Approve and Reject link per ticket."""
    expires_at = sent_at + timedelta(days=settings.link_days)
    links = {
        ticket["ticket_id"]: {
            decision: link_for(
                settings.public_base_url,
                make_token(ticket["ticket_id"], decision, expires_at, settings.link_secret),
            )
            for decision in DECISION_CODES
        }
        for ticket in batch
    }
    return build_approval_email(
        batch, settings.user_name, settings.manager_name, links, expires_at
    )


def _safe_error(exc: Exception) -> str:
    """Exception type and message with any secret masked, for the log."""
    detail = f"{type(exc).__name__}: {exc}"
    for secret in (SMTP_PASSWORD, APPROVAL_LINK_SECRET):
        if secret:
            detail = detail.replace(secret, "***")
    return detail


def _display_date(timestamp: str) -> str:
    return parse_timestamp(timestamp).strftime(DATE_FORMAT)


def _nothing_to_send(service: EscalationService) -> str:
    waiting = service.waiting_for_reply()
    if not waiting:
        return "No urgent open tickets need a decision."
    verb = "is" if len(waiting) == 1 else "are"
    return (
        f"Nothing to send yet. {plural(len(waiting), 'ticket')} {verb} waiting for "
        "the manager's reply; the next reminder is due "
        f"{_display_date(waiting[0]['reminder_due_at'])}."
    )


@app.get("/approvals/batch/preview")
def approval_batch_preview(
    settings: ApprovalSettings = Depends(require_approval_names),
    service: EscalationService = Depends(get_escalation_service),
):
    # The same links that would be sent now.
    require_link_settings(settings)
    email = _batch_email(settings, service.approval_batch(), service.clock())
    return {"to": settings.manager_name, "from": settings.user_name, **email}


@app.post("/approvals/batch/send")
def approval_batch_send(
    settings: ApprovalSettings = Depends(require_approval_names),
    service: EscalationService = Depends(get_escalation_service),
    sender: SmtpEmailSender = Depends(get_email_sender),
):
    missing = settings.missing_email_setting()
    if missing:
        raise _not_configured(missing)
    require_link_settings(settings)

    batch = service.approval_batch()
    if not batch:
        raise HTTPException(status_code=409, detail=_nothing_to_send(service))

    missing = sender.missing_setting()
    if missing:
        raise _not_configured(missing)

    # Don't email the manager if the requests can't be saved afterwards.
    check_log_writable(service.request_log_path)
    check_log_writable(service.email_log_path)

    # request_approval() below only accepts known managers.
    service.add_manager(settings.manager_name)
    sent_at = service.clock()
    email = _batch_email(settings, batch, sent_at)
    message = build_message(
        email,
        settings.user_name,
        settings.user_email,
        settings.manager_name,
        settings.manager_email,
    )
    try:
        sender.send(message)
    except Exception as exc:
        # Log the failure type and message, never the SMTP password.
        logger.error("Approval email could not be sent: %s", _safe_error(exc))
        raise HTTPException(
            status_code=502, detail="Approval email could not be sent."
        ) from None

    # Only after a successful send: new tickets move to awaiting_decision.
    newly_requested, reminders = [], []
    for ticket in batch:
        if ticket["send_reason"] != "new":
            reminders.append(ticket["ticket_id"])
            continue
        try:
            service.request_approval(
                ticket["ticket_id"], settings.user_name, settings.manager_name
            )
            newly_requested.append(ticket["ticket_id"])
        except AlreadyRequested:
            reminders.append(ticket["ticket_id"])

    # One write for the whole email, so a failure leaves no partial rows.
    try:
        service.log_emails(batch, sent_at)
    except LogWriteError as exc:
        logger.error("Could not write %s: %s", exc.file_name, exc.__cause__)
        raise HTTPException(
            status_code=503,
            detail=(
                f"The approval email was sent, but {exc.file_name} could not be "
                "saved, so reminders may come back early. Close it if it is open "
                "in Excel."
            ),
        ) from None

    return {
        "sent": True,
        "ticket_ids": email["ticket_ids"],
        "newly_requested": newly_requested,
        "reminders": reminders,
        "next_reminder_due_at": service.next_reminder_due_at(),
    }


# Confirmation page for the Approve/Reject links ------------------------------
#
# GET only shows a page: email security scanners and mail clients open links
# by themselves, so nothing may be recorded until the manager presses Confirm.


def _checked_link(
    token: str,
    settings: ApprovalSettings,
    service: EscalationService,
    no_decision_status: int,
):
    """(claims, ticket, None) if the link can be confirmed, else (None, None, page)."""

    def blocked(content: str, status_code: int):
        return None, None, _page_response(content, status_code)

    if not settings.link_secret or not settings.manager_name:
        return blocked(pages.not_configured_page(), 503)
    try:
        claims = read_token(token, settings.link_secret, service.clock())
    except InvalidLink:
        return blocked(pages.invalid_page(), 400)
    except ExpiredLink as exc:
        ticket_id = exc.claims.ticket_id
        escalation = service.escalation_for(ticket_id) if ticket_id in service.tickets else None
        if escalation and escalation["decision"]:
            return blocked(pages.already_decided_page(ticket_id, escalation), 409)
        return blocked(pages.expired_page(), 410)

    ticket_id = claims.ticket_id
    if ticket_id not in service.tickets:
        return blocked(
            pages.no_decision_needed_page(
                ticket_id, "is not in the Help Desk export, so no decision is needed."
            ),
            no_decision_status,
        )
    escalation = service.escalation_for(ticket_id)
    if escalation and escalation["decision"]:
        return blocked(pages.already_decided_page(ticket_id, escalation), 409)
    ticket = service.ticket_summary(ticket_id)
    if not service.is_urgent_open(ticket):
        return blocked(
            pages.no_decision_needed_page(
                ticket_id, "is no longer an urgent open ticket, so no decision is needed."
            ),
            no_decision_status,
        )
    if ticket["approval_stage"] != "awaiting_decision":
        return blocked(
            pages.no_decision_needed_page(
                ticket_id, "is not waiting for approval, so no decision is needed."
            ),
            no_decision_status,
        )
    return claims, ticket, None


@app.get(RESPOND_PATH, response_class=HTMLResponse)
def approval_respond_page(
    token: str = "",
    settings: ApprovalSettings = Depends(get_approval_settings),
    service: EscalationService = Depends(get_escalation_service),
):
    """Shows the ticket and a Confirm button. Never records anything."""
    claims, ticket, page = _checked_link(token, settings, service, no_decision_status=200)
    if page:
        return page
    return _page_response(
        pages.confirm_page(ticket, claims.decision, f"{RESPOND_PATH}?token={token}")
    )


def _send_result_email(
    settings: ApprovalSettings,
    sender: SmtpEmailSender,
    ticket: dict,
    decision: str,
    decided_at: datetime,
) -> bool:
    """Email the result to the user, manager in Cc. False (logged) on failure."""
    ticket_id = ticket["ticket_id"]
    missing = settings.missing_email_setting() or sender.missing_setting()
    if missing:
        logger.warning("Result email for %s not sent: %s is not set.", ticket_id, missing)
        return False
    email = build_result_email(ticket, decision, settings.manager_name, decided_at)
    message = build_result_message(
        email,
        settings.user_name,
        settings.user_email,
        settings.manager_name,
        settings.manager_email,
    )
    try:
        sender.send(message)
    except Exception as exc:
        logger.warning(
            "Result email for %s could not be sent: %s", ticket_id, _safe_error(exc)
        )
        return False
    return True


@app.post(RESPOND_PATH, response_class=HTMLResponse)
def approval_respond_confirm(
    token: str = "",
    settings: ApprovalSettings = Depends(get_approval_settings),
    service: EscalationService = Depends(get_escalation_service),
    sender: SmtpEmailSender = Depends(get_email_sender),
):
    """Checks the link again and records the decision as the manager."""
    claims, ticket, page = _checked_link(token, settings, service, no_decision_status=409)
    if page:
        return page

    ticket_id, decision = claims.ticket_id, claims.decision
    try:
        service.record_decision(ticket_id, decision, settings.manager_name)
    except AlreadyDecided:
        # Decided by another click between the check and now.
        escalation = service.escalation_for(ticket_id)
        return _page_response(pages.already_decided_page(ticket_id, escalation), 409)
    except (TicketNotFound, NotAnEscalation):
        return _page_response(
            pages.no_decision_needed_page(
                ticket_id, "is not waiting for approval, so no decision is needed."
            ),
            409,
        )

    decided_at = service.recorded[ticket_id]["decided_at"]
    # The decision stays recorded even if this email fails.
    email_sent = _send_result_email(settings, sender, ticket, decision, decided_at)
    return _page_response(
        pages.recorded_page(
            ticket_id, decision, settings.manager_name, decided_at, email_sent
        )
    )


@app.post("/approvals/reply/preview")
def approval_reply_preview(
    request: ReplyRequest,
    settings: ApprovalSettings = Depends(require_approval_names),
    service: EscalationService = Depends(get_escalation_service),
):
    try:
        review = service.review_reply(request.reply_text)
    except NoTicketsInReply as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"manager": settings.manager_name, **review}


@app.post("/approvals/reply/record")
def approval_reply_record(
    request: ReplyRequest,
    settings: ApprovalSettings = Depends(require_approval_names),
    service: EscalationService = Depends(get_escalation_service),
):
    # Parsed again here: the client's preview is never trusted.
    try:
        result = service.record_reply(request.reply_text, settings.manager_name)
    except NoTicketsInReply as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"manager": settings.manager_name, **result}


@app.post("/approvals/{ticket_id}/request")
def request_manager_approval(
    ticket_id: TicketId,
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
    category: Optional[str] = CategoryQuery,
    priority: Optional[str] = None,
    open_only: bool = False,
    escalated: Optional[bool] = None,
    service: EscalationService = Depends(get_escalation_service),
):
    # Case-insensitive, but only known values, so a typo isn't an empty list.
    _require_one_of("status", status, HELPDESK_STATUSES)
    _require_one_of("priority", priority, HELPDESK_PRIORITIES)
    return service.list_tickets(
        status=status,
        category=category,
        priority=priority,
        open_only=open_only,
        escalated=escalated,
    )


@app.get("/helpdesk/tickets/{ticket_id}")
def get_helpdesk_ticket(
    ticket_id: TicketId,
    service: EscalationService = Depends(get_escalation_service),
):
    try:
        return service.ticket_view(ticket_id)
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="ticket not found") from None


@app.get("/escalations")
def list_escalations(
    state: Optional[Literal["pending", "accepted", "rejected"]] = None,
    category: Optional[str] = CategoryQuery,
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
    ticket_id: TicketId,
    request: DecisionRequest,
    service: EscalationService = Depends(get_escalation_service),
):
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


# Health check --------------------------------------------------------------
#
# Must stay above the static mount below, which would otherwise answer
# /health with a 404 page.


def _file_status(path: str, required_column: Optional[str] = None) -> str:
    """ok, missing, or unreadable. Reads at most the first 64 KB."""
    file_path = Path(path)
    if not file_path.is_file():
        return "missing"
    try:
        with open(file_path, newline="", encoding="utf-8-sig") as file:
            start = file.read(65_536)
    except (OSError, UnicodeError):
        return "unreadable"
    if required_column:
        header = next(csv.reader(start.splitlines()[:1]), [])
        if required_column not in [column.strip() for column in header]:
            return "unreadable"
    return "ok"


def _logs_writable() -> str:
    """Whether the logs could be appended to. Creates and changes nothing."""
    for path in (
        Path(DECISION_LOG_PATH),
        Path(APPROVAL_REQUEST_LOG_PATH),
        Path(APPROVAL_EMAIL_LOG_PATH),
    ):
        if path.exists():
            if not os.access(path, os.W_OK):
                return "not_writable"
            continue
        folder = path.parent
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        if not os.access(folder, os.W_OK):
            return "not_writable"
    return "ok"


@app.get("/health")
def health(
    settings: ApprovalSettings = Depends(get_approval_settings),
    sender: SmtpEmailSender = Depends(get_email_sender),
):
    """Fast, local-only status for monitoring. Always 200 while running.

    Never calls Gemini or the mail server, and never includes keys,
    addresses, names, or paths: only fixed status words.
    """
    files = {
        "ticket_data": _file_status(DATA_PATH),
        "helpdesk_export": _file_status(HELPDESK_EXPORT_PATH, "ticket_id"),
        "escalation_tracker": _file_status(ESCALATION_TRACKER_PATH),
        "logs_writable": _logs_writable(),
    }
    email_ready = (
        settings.missing_name_setting() is None
        and settings.missing_email_setting() is None
        and sender.missing_setting() is None
    )
    return {
        "status": "ok" if all(v == "ok" for v in files.values()) else "degraded",
        "time": datetime.now().isoformat(timespec="seconds"),
        "checks": {
            **files,
            "triage_ai": (
                "configured" if os.getenv("GEMINI_API_KEY", "").strip() else "not_configured"
            ),
            "approval_email": "configured" if email_ready else "not_configured",
        },
    }


# Preserve the original Task 3 static frontend
app.mount(
    "/",
    StaticFiles(directory=str(WEB_DIR), html=True),
    name="web",
)

