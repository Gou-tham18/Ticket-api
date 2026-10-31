"""Task 6 production basics: error handling, input validation, and /health."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.escalations import EscalationService
from app.main import ApprovalSettings, app

SAMPLE_EXPORT = Path("data/helpdesk_export_sample.csv")
SAMPLE_TRACKER = Path("data/escalation_tracker_sample.csv")
SAMPLE_TICKETS = Path("data/tickets_sample.csv")

EXPORT_HEADER = (
    "ticket_id,created_at,status,priority,category,assigned_to,"
    "customer_email,labels,refund_amount\n"
)
TRACKER_HEADER = "ticket_id,requested_by,approver,requested_at,decision,decided_at,notes\n"

SETTINGS = ApprovalSettings(
    user_name="Riya",
    user_email="riya@example.org",
    manager_name="Mara",
    manager_email="mara@example.org",
    public_base_url="https://approvals.example.org",
    link_secret="test-link-secret-xxxxxxxxxxxxxxxxxxxxxxxx",
)


class FakeSender:
    def __init__(self):
        self.sent = []

    def missing_setting(self):
        return None

    def send(self, message):
        self.sent.append(message)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Copies of the sample files, wired into app.main's real service loader."""
    files = {
        "export": tmp_path / "export.csv",
        "tracker": tmp_path / "tracker.csv",
        "decisions": tmp_path / "decisions.csv",
        "requests": tmp_path / "requests.csv",
        "emails": tmp_path / "emails.csv",
    }
    shutil.copyfile(SAMPLE_EXPORT, files["export"])
    shutil.copyfile(SAMPLE_TRACKER, files["tracker"])
    monkeypatch.setattr(main, "HELPDESK_EXPORT_PATH", str(files["export"]))
    monkeypatch.setattr(main, "ESCALATION_TRACKER_PATH", str(files["tracker"]))
    monkeypatch.setattr(main, "DECISION_LOG_PATH", str(files["decisions"]))
    monkeypatch.setattr(main, "APPROVAL_REQUEST_LOG_PATH", str(files["requests"]))
    monkeypatch.setattr(main, "APPROVAL_EMAIL_LOG_PATH", str(files["emails"]))
    monkeypatch.setattr(main, "APPROVAL_MANAGER_NAME", "Mara")
    monkeypatch.setattr(main, "_escalation_service", None)
    return files


@pytest.fixture
def client(paths):
    sender = FakeSender()
    app.dependency_overrides[main.get_approval_settings] = lambda: SETTINGS
    app.dependency_overrides[main.get_email_sender] = lambda: sender
    test_client = TestClient(app)
    test_client.sender = sender
    yield test_client
    app.dependency_overrides.clear()


# A1.1 Ticket CSV ---------------------------------------------------------------


def test_app_imports_and_starts_with_a_missing_ticket_csv(tmp_path):
    env = {**os.environ, "TICKETS_DATA_PATH": str(tmp_path / "gone.csv")}
    script = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "r = TestClient(app).get('/tickets')\n"
        "print(r.status_code, r.json()['detail'])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "503 Ticket data file 'gone.csv' was not found. Check TICKETS_DATA_PATH."
        in result.stdout
    )


@pytest.mark.parametrize("path", ["/tickets", "/tickets/TCK-1001", "/summary"])
def test_missing_ticket_csv_gives_503_naming_the_file_only(tmp_path, monkeypatch, path):
    monkeypatch.setattr(main, "DATA_PATH", str(tmp_path / "gone.csv"))
    monkeypatch.setattr(main, "TICKETS", None)

    response = TestClient(app).get(path)

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Ticket data file 'gone.csv' was not found. Check TICKETS_DATA_PATH."
    )
    assert str(tmp_path) not in response.text


def test_unreadable_ticket_csv_gives_503(tmp_path, monkeypatch):
    bad = tmp_path / "tickets.csv"
    bad.write_bytes(b"ticket_id,created_at\n\xff\xfe\xfa not utf-8\n")
    monkeypatch.setattr(main, "DATA_PATH", str(bad))
    monkeypatch.setattr(main, "TICKETS", None)

    response = TestClient(app).get("/summary")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Ticket data file 'tickets.csv' could not be read. Check TICKETS_DATA_PATH."
    )


def test_ticket_data_recovers_when_the_file_appears(tmp_path, monkeypatch):
    target = tmp_path / "tickets.csv"
    monkeypatch.setattr(main, "DATA_PATH", str(target))
    monkeypatch.setattr(main, "TICKETS", None)
    client = TestClient(app)
    assert client.get("/tickets").status_code == 503

    shutil.copyfile(SAMPLE_TICKETS, target)

    assert client.get("/tickets").status_code == 200


def test_other_endpoints_work_without_ticket_csv(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_PATH", str(tmp_path / "gone.csv"))
    monkeypatch.setattr(main, "TICKETS", None)

    with patch(
        "app.triage_service.call_model",
        return_value={"priority": "low", "suggested_reply": "x" * 40},
    ):
        triage = client.post("/triage", json={"subject": "Login", "text": "Cannot sign in"})

    assert triage.status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.get("/approvals/urgent-open").status_code == 200


# A1.2 Help Desk export --------------------------------------------------------

TASK5_GETS = ["/dashboard", "/approvals/urgent-open", "/helpdesk/tickets", "/escalations"]


@pytest.mark.parametrize("path", TASK5_GETS)
def test_missing_export_gives_503(client, paths, path):
    paths["export"].unlink()

    response = client.get(path)

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Help Desk export 'export.csv' was not found. Check HELPDESK_EXPORT_PATH."
    )


def test_export_without_ticket_id_column_gives_503(client, paths):
    paths["export"].write_text("id,status\n1,open\n", encoding="utf-8")

    response = client.get("/dashboard")

    assert response.status_code == 503
    assert "has no ticket_id column" in response.json()["detail"]


def test_unreadable_export_gives_503(client, paths):
    paths["export"].write_bytes(EXPORT_HEADER.encode() + b"TCK-1,\xff\xfe\xfa\n")

    response = client.get("/dashboard")

    assert response.status_code == 503
    assert "could not be read" in response.json()["detail"]
    assert "export.csv" in response.json()["detail"]


def test_service_recovers_after_export_is_restored(client, paths):
    paths["export"].unlink()
    assert client.get("/dashboard").status_code == 503

    shutil.copyfile(SAMPLE_EXPORT, paths["export"])

    assert client.get("/dashboard").status_code == 200


# A1.3 Tracker ---------------------------------------------------------------------


def test_missing_tracker_is_treated_as_empty_and_reported(client, paths):
    paths["tracker"].unlink()

    dashboard = client.get("/dashboard")
    issues = client.get("/escalations/data-issues").json()

    assert dashboard.status_code == 200
    assert dashboard.json()["total_tickets"] == 120
    assert any(
        i["source"] == "escalation_tracker" and "tracker.csv" in i["problem"] for i in issues
    )


# A1.4 Log files -------------------------------------------------------------------

LOCKED = "Close it if it is open in Excel and try again."


def lock(path: Path):
    """Make a log path impossible to append to, like a file open in Excel."""
    path.mkdir()


def test_missing_logs_are_created_on_first_write(client, paths):
    response = client.post(
        "/approvals/TCK-5110/request", json={"requested_by": "Riya", "approver": "Mara"}
    )

    assert response.status_code == 200
    assert paths["requests"].read_text(encoding="utf-8").startswith("ticket_id,")


def test_locked_decision_log_gives_503_and_changes_nothing(client, paths):
    lock(paths["decisions"])

    response = client.post(
        "/escalations/TCK-5007/decision", json={"decision": "Accept", "decided_by": "Mara"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == f"Could not save to decisions.csv. {LOCKED}"
    ticket = client.get("/helpdesk/tickets/TCK-5007").json()
    assert ticket["escalation"]["state"] == "pending"


def test_locked_request_log_gives_503_and_changes_nothing(client, paths):
    lock(paths["requests"])

    response = client.post(
        "/approvals/TCK-5110/request", json={"requested_by": "Riya", "approver": "Mara"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == f"Could not save to requests.csv. {LOCKED}"
    ticket = client.get("/helpdesk/tickets/TCK-5110").json()
    assert ticket["escalation"]["in_tracker"] is False


def test_locked_request_log_stops_the_email_being_sent(client, paths):
    lock(paths["requests"])

    response = client.post("/approvals/batch/send")

    assert response.status_code == 503
    assert "requests.csv" in response.json()["detail"]
    assert client.sender.sent == []


def test_locked_decision_log_records_nothing_from_a_reply(client, paths):
    client.post("/approvals/batch/send")
    lock(paths["decisions"])

    response = client.post(
        "/approvals/reply/record",
        json={"reply_text": "TCK-5007 APPROVE\nTCK-5050 REJECT\n"},
    )

    assert response.status_code == 503
    pending = {t["ticket_id"] for t in client.get("/escalations?state=pending").json()}
    assert {"TCK-5007", "TCK-5050"} <= pending


def test_failed_write_leaves_no_partial_row(tmp_path):
    from app.escalations import LogWriteError, _append_csv_row

    target = tmp_path / "log.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    before = target.read_bytes()

    with patch("builtins.open", side_effect=PermissionError("locked")):
        with pytest.raises(LogWriteError):
            _append_csv_row(target, ["a", "b"], {"a": "3", "b": "4"})

    assert target.read_bytes() == before


# A1.5 Bad values --------------------------------------------------------------------


def test_short_and_long_export_rows_are_kept_and_reported(client, paths):
    paths["export"].write_text(
        EXPORT_HEADER
        + "TCK-1,2026-10-05 13:05,open,urgent,Billing\n"
        + "TCK-2,2026-10-05 13:05,open,low,Login,sam,a@example.com,,,surplus\n"
        + "TCK-3,not a date,open,urgent,Refunds,ken,b@example.com,esc,lots\n",
        encoding="utf-8",
    )

    dashboard = client.get("/dashboard")
    problems = {(i["ticket_id"], i["problem"]) for i in client.get("/escalations/data-issues").json()}

    assert dashboard.status_code == 200
    assert dashboard.json()["total_tickets"] == 3
    assert client.get("/approvals/urgent-open").status_code == 200
    assert any(t == "TCK-1" and "fewer fields" in p for t, p in problems)
    assert any(t == "TCK-2" and "more fields" in p for t, p in problems)
    assert any(t == "TCK-3" and "refund_amount" in p for t, p in problems)


def test_bad_tracker_and_log_values_do_not_crash(client, paths):
    paths["tracker"].write_text(
        TRACKER_HEADER + "TCK-5007,Zoe,Joyce,yesterday,maybe,soon\n", encoding="utf-8"
    )
    paths["decisions"].write_text("ticket_id,decision\nTCK-5050,Accept,extra\n", encoding="utf-8")

    assert client.get("/dashboard").status_code == 200
    problems = [i["problem"] for i in client.get("/escalations/data-issues").json()]
    assert any("requested_at" in p for p in problems)


# A1.6 Unexpected errors ------------------------------------------------------------


def test_unexpected_error_returns_500_with_error_id(client, caplog, monkeypatch):
    monkeypatch.setattr(
        EscalationService, "dashboard", lambda self: (_ for _ in ()).throw(KeyError("boom"))
    )

    response = client.get("/dashboard", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == (
        "Something went wrong on the server. Please try again, and if it keeps "
        "happening, report the time and this error ID."
    )
    assert len(body["error_id"]) == 8
    assert "Traceback" not in response.text and "KeyError" not in response.text
    # The full traceback is logged under the same ID.
    assert body["error_id"] in caplog.text
    assert "KeyError" in caplog.text
    # The browser can read it: CORS headers are still added.
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_specific_errors_are_unchanged(client):
    assert client.get("/helpdesk/tickets/TCK-404").status_code == 404
    assert client.get("/tickets/TCK-404").status_code == 404
    with patch("app.triage_service.call_model", side_effect=RuntimeError("model down")):
        response = client.post("/triage", json={"subject": "Login", "text": "Cannot sign in"})
    assert response.status_code == 502
    assert response.json() == {"detail": "Ticket triage service failed."}


# A2 Input validation -------------------------------------------------------------


def assert_422(response, message):
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["message"] == message
    # FastAPI's shape is kept: a list of objects with loc and msg.
    assert body["detail"][0]["msg"] == message
    assert isinstance(body["detail"][0]["loc"], list)


@pytest.mark.parametrize(
    "body, message",
    [
        ({"text": "Cannot sign in"}, "subject is required."),
        ({"subject": "x" * 501, "text": "Cannot sign in"}, "subject must be 500 characters or fewer."),
        ({"subject": "   ", "text": "Cannot sign in"}, "subject must not be blank."),
        ({"subject": "Login", "text": ""}, "text must not be blank."),
        ({"subject": 5, "text": "Cannot sign in"}, "subject must be text."),
    ],
)
def test_triage_validation_messages(body, message):
    assert_422(TestClient(app).post("/triage", json=body), message)


def test_invalid_json_body():
    response = TestClient(app).post(
        "/triage", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert_422(response, "The request body is not valid JSON.")


@pytest.mark.parametrize(
    "query, message",
    [
        ("page=0", "page must be 1 or more."),
        ("size=500", "size must be 100 or less."),
        ("page=two", "page must be a whole number."),
    ],
)
def test_task3_query_messages(query, message):
    assert_422(TestClient(app).get(f"/tickets?{query}"), message)


@pytest.mark.parametrize(
    "body, message",
    [
        ({"decision": "approved", "decided_by": "Mara"}, "decision must be Accept or Reject."),
        ({"decision": "Accept", "decided_by": "   "}, "decided_by must not be blank."),
        ({"decision": "Accept", "decided_by": ""}, "decided_by must not be blank."),
        ({"decision": "Accept"}, "decided_by is required."),
        ({"decision": "Accept", "decided_by": "x" * 101}, "decided_by must be 100 characters or fewer."),
    ],
)
def test_decision_validation_messages(client, body, message):
    assert_422(client.post("/escalations/TCK-5007/decision", json=body), message)


@pytest.mark.parametrize(
    "body, message",
    [
        ({"requested_by": " ", "approver": "Mara"}, "requested_by must not be blank."),
        ({"requested_by": "Riya", "approver": "\t"}, "approver must not be blank."),
    ],
)
def test_blank_names_on_approval_request(client, body, message):
    assert_422(client.post("/approvals/TCK-5110/request", json=body), message)


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/helpdesk/tickets/5007", None),
        ("get", "/helpdesk/tickets/tck-5007", None),
        ("post", "/approvals/TCK-5007x/request", {"requested_by": "Riya", "approver": "Mara"}),
        ("post", "/escalations/TCK-12345678901/decision", {"decision": "Accept", "decided_by": "Mara"}),
    ],
)
def test_task5_ticket_ids_are_validated(client, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body else {}))
    assert_422(response, "Ticket IDs look like TCK-5007.")


def test_task3_ticket_route_keeps_its_behaviour():
    assert TestClient(app).get("/tickets/not-an-id").status_code == 404


@pytest.mark.parametrize(
    "query, message",
    [
        ("status=pending", "status must be one of: open, in_progress, resolved, closed."),
        ("priority=critical", "priority must be one of: urgent, high, normal, low."),
    ],
)
def test_helpdesk_filters_list_allowed_values(client, query, message):
    assert_422(client.get(f"/helpdesk/tickets?{query}"), message)


def test_helpdesk_filters_stay_case_insensitive(client):
    tickets = client.get("/helpdesk/tickets?status=OPEN&priority=Urgent").json()
    assert tickets and all(t["status"] == "open" and t["priority"] == "urgent" for t in tickets)


@pytest.mark.parametrize("path", ["/helpdesk/tickets", "/escalations", "/approvals/urgent-open"])
def test_category_is_limited_to_50_characters(client, path):
    assert_422(client.get(f"{path}?category={'x' * 51}"), "category must be 50 characters or fewer.")
    assert client.get(f"{path}?category=Billing").status_code == 200


@pytest.mark.parametrize("path", ["/approvals/reply/preview", "/approvals/reply/record"])
@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_blank_reply_text(client, path, text):
    assert_422(client.post(path, json={"reply_text": text}), "Paste the manager's reply before checking it.")


def test_literal_filter_message(client):
    assert_422(client.get("/escalations?state=maybe"), "state must be pending, accepted or rejected.")


# A3 Health check -------------------------------------------------------------------


@pytest.fixture
def health_env(paths, tmp_path, monkeypatch):
    tickets = tmp_path / "tickets.csv"
    shutil.copyfile(SAMPLE_TICKETS, tickets)
    monkeypatch.setattr(main, "DATA_PATH", str(tickets))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key-123")
    return {**paths, "tickets": tickets}


def test_health_all_ok(client, health_env):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {
        "ticket_data": "ok",
        "helpdesk_export": "ok",
        "escalation_tracker": "ok",
        "logs_writable": "ok",
        "triage_ai": "configured",
        "approval_email": "configured",
    }
    assert "T" in body["time"]


def test_health_does_not_create_logs(client, health_env):
    client.get("/health")

    assert not health_env["decisions"].exists()
    assert not health_env["requests"].exists()


def test_health_missing_export_is_degraded_but_200(client, health_env):
    health_env["export"].unlink()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["helpdesk_export"] == "missing"


def test_health_unreadable_files(client, health_env):
    health_env["export"].write_text("id,status\n", encoding="utf-8")
    health_env["tickets"].write_bytes(b"ticket_id\n\xff\xfe\xfa\n")

    checks = client.get("/health").json()["checks"]

    assert checks["helpdesk_export"] == "unreadable"
    assert checks["ticket_data"] == "unreadable"


def test_health_without_gemini_or_smtp_is_still_ok(health_env, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(main, "SMTP_HOST", "")
    monkeypatch.setattr(main, "APPROVAL_USER_NAME", "")

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["triage_ai"] == "not_configured"
    assert body["checks"]["approval_email"] == "not_configured"


def test_health_never_contains_secrets_names_or_paths(health_env, monkeypatch):
    monkeypatch.setattr(main, "APPROVAL_USER_NAME", "Riya")
    monkeypatch.setattr(main, "APPROVAL_USER_EMAIL", "riya@example.org")
    monkeypatch.setattr(main, "APPROVAL_MANAGER_NAME", "Mara")
    monkeypatch.setattr(main, "APPROVAL_MANAGER_EMAIL", "mara@example.org")
    monkeypatch.setattr(main, "SMTP_HOST", "smtp.example.org")
    monkeypatch.setattr(main, "SMTP_USERNAME", "riya@example.org")
    monkeypatch.setattr(main, "SMTP_PASSWORD", "fake-smtp-password-456")

    response = TestClient(app).get("/health")
    text = response.text

    assert response.json()["checks"]["approval_email"] == "configured"
    for secret in [
        "fake-gemini-key-123", "fake-smtp-password-456", "@", "Riya", "Mara",
        "smtp.example.org", str(health_env["tickets"].parent), ".csv",
    ]:
        assert secret not in text


def test_health_is_not_swallowed_by_the_static_mount():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert "status" in response.json()
    # The static page is still served at /.
    assert TestClient(app).get("/").headers["content-type"].startswith("text/html")
