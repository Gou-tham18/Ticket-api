
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app.ticket_summary import process_tickets_file

DATA_PATH = os.environ["TICKETS_DATA_PATH"]
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="ticket-api")


def load_tickets(path):
    import csv
    from datetime import datetime

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


@app.get("/tickets")
def list_tickets(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
):
    start = (page - 1) * size
    return [public(ticket) for ticket in TICKETS[start : start + size]]


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    for ticket in TICKETS:
        if ticket["ticket_id"] == ticket_id:
            return public(ticket)

    raise HTTPException(status_code=404, detail="ticket not found")


@app.get("/summary")
def summary():
    by_category, average_hours = process_tickets_file(DATA_PATH)

    return {
        "total": sum(by_category.values()),
        "by_category": by_category,
        "average_resolution_hours": average_hours,
    }


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


