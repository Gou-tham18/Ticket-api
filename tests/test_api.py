
import csv
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

DATA_PATH = Path("data/tickets_sample.csv")
FMT = "%Y-%m-%d %H:%M"


def load_csv_tickets():
    with DATA_PATH.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_summary_matches_csv():
    tickets = load_csv_tickets()
    body = client.get("/summary").json()

    expected_categories = {}
    for ticket in tickets:
        category = ticket["category"]
        expected_categories[category] = (
            expected_categories.get(category, 0) + 1
        )

    assert body["total"] == len(tickets)
    assert body["by_category"] == expected_categories


def test_summary_average_uses_resolved_tickets_only():
    tickets = load_csv_tickets()
    durations = []

    for ticket in tickets:
        if ticket["resolved_at"]:
            created = datetime.strptime(ticket["created_at"], FMT)
            resolved = datetime.strptime(ticket["resolved_at"], FMT)
            durations.append(
                (resolved - created).total_seconds() / 3600
            )

    expected_average = round(sum(durations) / len(durations), 2)
    body = client.get("/summary").json()

    assert body["average_resolution_hours"] == expected_average


def test_first_page_starts_with_first_csv_ticket():
    tickets = load_csv_tickets()
    body = client.get("/tickets?page=1&size=10").json()

    assert len(body) == 10
    assert body[0]["ticket_id"] == tickets[0]["ticket_id"]


def test_second_page_starts_with_eleventh_csv_ticket():
    tickets = load_csv_tickets()
    body = client.get("/tickets?page=2&size=10").json()

    assert len(body) == 10
    assert body[0]["ticket_id"] == tickets[10]["ticket_id"]


def test_unknown_ticket_is_404():
    response = client.get("/tickets/TCK-0000")

    assert response.status_code == 404


def test_cors_allows_frontend_opened_by_lan_address():
    origin = "http://192.168.1.5:5173"
    response = client.get("/summary", headers={"Origin": origin})

    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_unknown_origins():
    for origin in ("http://evil.example.com:5173", "http://192.168.1.5:8080"):
        response = client.get("/summary", headers={"Origin": origin})

        assert "access-control-allow-origin" not in response.headers


def test_summary_uses_day1_summary_module(monkeypatch):
    import app.main as main_module

    def fake_summary(file_path):
        return {"Billing": 3, "Technical": 2}, 12.5

    monkeypatch.setattr(
        main_module,
        "process_tickets_file",
        fake_summary,
    )

    response = client.get("/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total": 5,
        "by_category": {
            "Billing": 3,
            "Technical": 2,
        },
        "average_resolution_hours": 12.5,
    }


def test_day1_summary_module_matches_sample_csv():
    from app.ticket_summary import process_tickets_file

    categories, average_hours = process_tickets_file(
        DATA_PATH
    )

    assert sum(categories.values()) == 60
    assert categories == {
        "Billing": 9,
        "Shipping": 9,
        "Refunds": 12,
        "Technical": 12,
        "Account": 8,
        "Login": 10,
    }
    assert average_hours == 25.27


def test_load_tickets_accepts_messy_csv(tmp_path):
    from app.main import load_tickets

    path = tmp_path / "tickets.csv"
    path.write_text(
        "﻿ticket_id,created_at,resolved_at,category,priority,status\n"
        "TCK-1, 2026-03-02 08:23 ,02/03/2026 17:23,Billing,urgent,closed\n"
        ",,,,,\n"
        "TCK-2,not a date,,Login,low,open\n"
        "TCK-3,2026-03-03 09:00,,Shipping,normal,open\n",
        encoding="utf-8",
    )

    tickets = load_tickets(path)

    assert [t["ticket_id"] for t in tickets] == ["TCK-1", "TCK-3"]
    assert tickets[0]["created_at"] == "2026-03-02 08:23"
    assert tickets[0]["resolved"].day == 2
    assert tickets[1]["resolved"] is None
