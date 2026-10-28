
import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.ticket_summary import process_tickets_file
from app.triage_service import TriageRequest, triage_ticket


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
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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


# Preserve the original Task 3 static frontend
app.mount(
    "/",
    StaticFiles(directory=str(WEB_DIR), html=True),
    name="web",
)

