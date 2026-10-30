"""Email approval round trip: dashboard, approval email, and pasted reply."""

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.approval_email import SmtpSettings, format_created, format_refund
from app.approval_reply import NoTicketsInReply, parse_reply
from app.escalations import EscalationService, is_escalation_tag_set
from app.main import (
    ApprovalSettings,
    app,
    get_approval_settings,
    get_email_sender,
    get_escalation_service,
)

SAMPLE_EXPORT = Path("data/helpdesk_export_sample.csv")
SAMPLE_TRACKER = Path("data/escalation_tracker_sample.csv")

NOW = datetime(2026, 10, 20, 9, 15)
SMTP_SECRET = "s3cret-smtp-password"

SETTINGS = ApprovalSettings(
    user_name="Riya",
    user_email="riya@example.org",
    manager_name="Mara",
    manager_email="mara@example.org",
)


class FakeSender:
    """Stands in for SmtpEmailSender so no network connection is opened."""

    def __init__(self, missing=None, fail=False):
        self.missing = missing
        self.fail = fail
        self.sent = []

    def missing_setting(self):
        return self.missing

    def send(self, message):
        if self.fail:
            raise ConnectionRefusedError(f"login failed for password {SMTP_SECRET}")
        self.sent.append(message)


def read_rows(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


@pytest.fixture
def paths(tmp_path):
    """Copies of the sample files plus empty logs, so data/ is never touched."""
    export = tmp_path / "export.csv"
    tracker = tmp_path / "tracker.csv"
    shutil.copyfile(SAMPLE_EXPORT, export)
    shutil.copyfile(SAMPLE_TRACKER, tracker)
    return {
        "export": export,
        "tracker": tracker,
        "decisions": tmp_path / "decisions.csv",
        "requests": tmp_path / "requests.csv",
    }


def make_service(paths, fixed_manager="Mara"):
    return EscalationService(
        paths["export"],
        paths["tracker"],
        paths["decisions"],
        clock=lambda: NOW,
        request_log_path=paths["requests"],
        fixed_manager=fixed_manager,
    )


@pytest.fixture
def service(paths):
    return make_service(paths)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def client(service, sender):
    app.dependency_overrides[get_escalation_service] = lambda: service
    app.dependency_overrides[get_approval_settings] = lambda: SETTINGS
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_settings(**changes):
    values = {**SETTINGS.__dict__, **changes}
    app.dependency_overrides[get_approval_settings] = lambda: ApprovalSettings(**values)


def contains_customer_email(body) -> bool:
    text = json.dumps(body)
    return "customer_email" in text or "@example.com" in text


# Configuration ---------------------------------------------------------------


@pytest.mark.parametrize("missing", ["user_name", "manager_name"])
@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/approvals/batch/preview", None),
        ("post", "/approvals/batch/send", None),
        ("post", "/approvals/reply/preview", {"reply_text": "TCK-5007 approve"}),
        ("post", "/approvals/reply/record", {"reply_text": "TCK-5007 approve"}),
    ],
)
def test_missing_user_or_manager_gives_503(client, missing, method, path, body):
    use_settings(**{missing: ""})

    response = getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code == 503
    assert f"APPROVAL_{missing.upper()}" in response.json()["detail"]


def test_rest_of_api_works_without_approval_settings(client):
    use_settings(user_name="", manager_name="")

    assert client.get("/dashboard").status_code == 200
    assert client.get("/approvals/urgent-open").status_code == 200


def test_config_exposes_names_but_no_addresses(client):
    body = client.get("/approvals/config").json()

    assert body == {
        "user_name": "Riya",
        "manager_name": "Mara",
        "configured": True,
        "email_configured": True,
    }
    assert "@" not in json.dumps(body)


def test_config_reports_missing_email_settings(client, sender):
    sender.missing = "SMTP_HOST"

    body = client.get("/approvals/config").json()

    assert body["configured"] is True
    assert body["email_configured"] is False


def test_fixed_manager_is_an_accepted_approver(service):
    assert "Mara" in service.managers
    # The tracker's own approvers are still there for the per-ticket form.
    assert {"Anil", "Joyce"} <= set(service.managers)


def test_smtp_settings_name_the_missing_setting():
    assert SmtpSettings().missing_setting() == "SMTP_HOST"
    assert SmtpSettings(host="h", username="u").missing_setting() == "SMTP_PASSWORD"
    assert SmtpSettings(host="localhost", port=1025).missing_setting() is None


# Approval stage bug --------------------------------------------------------


def test_decided_ticket_without_tracker_row_is_not_reported_as_not_requested(tmp_path):
    export = tmp_path / "export.csv"
    export.write_text(
        "ticket_id,created_at,status,priority,category,assigned_to,"
        "customer_email,labels,refund_amount\n"
        "TCK-1,2026-10-05 13:05,open,urgent,Billing,riya,a@example.com,esc,\n",
        encoding="utf-8",
    )
    tracker = tmp_path / "tracker.csv"
    tracker.write_text(
        "ticket_id,requested_by,approver,requested_at,decision,decided_at,notes\n",
        encoding="utf-8",
    )
    service = EscalationService(export, tracker, tmp_path / "decisions.csv")
    assert service.urgent_open_analysis()["tickets"][0]["approval_stage"] == "not_requested"

    service.record_decision("TCK-1", "Accept", "Anil")

    ticket = service.urgent_open_analysis()["tickets"][0]
    assert ticket["escalation"]["in_tracker"] is False
    assert ticket["escalation"]["state"] == "accepted"
    assert ticket["approval_stage"] == "accepted"


# Dashboard -----------------------------------------------------------------


def test_dashboard_counts_match_the_sample_csv(client):
    with open(SAMPLE_EXPORT, newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    open_rows = [r for r in rows if r["status"] in ("open", "in_progress")]
    urgent = {r["ticket_id"] for r in open_rows if r["priority"] == "urgent"}
    escalated = {r["ticket_id"] for r in open_rows if is_escalation_tag_set(r["labels"])}
    refund = {
        r["ticket_id"]
        for r in open_rows
        if r["refund_amount"] and float(r["refund_amount"]) > 200
    }

    body = client.get("/dashboard").json()

    assert body["total_tickets"] == 120
    assert body["open_tickets"] == 79
    assert body["attention"] == {
        "urgent_open": 10,
        "escalated_label": len(escalated),
        "refund_over_200": len(refund),
        "any_condition": len(urgent | escalated | refund),
    }
    assert [t["ticket_id"] for t in body["tickets"]] == [r["ticket_id"] for r in rows]


def test_dashboard_never_contains_customer_email(client):
    body = client.get("/dashboard").json()

    assert not contains_customer_email(body)
    assert all("customer_email" not in ticket for ticket in body["tickets"])


def test_dashboard_ticket_fields(client):
    tickets = {t["ticket_id"]: t for t in client.get("/dashboard").json()["tickets"]}

    assert tickets["TCK-5110"] == {
        "ticket_id": "TCK-5110",
        "category": "Billing",
        "priority": "urgent",
        "created_at": "2026-10-11 14:15",
        "status": "open",
        "is_open": True,
        "assigned_to": "lia",
        "labels": ["escalated", "vip"],
        "refund_amount": 199.0,
        "indicators": ["urgent_open", "escalated_label"],
        "approval_stage": "not_requested",
    }
    # Refund over 200 but resolved: closed tickets carry no indicators.
    assert tickets["TCK-5058"]["indicators"] == []
    assert tickets["TCK-5058"]["approval_stage"] is None
    assert tickets["TCK-5084"]["labels"] == []
    assert tickets["TCK-5084"]["refund_amount"] is None


def test_unreadable_refund_is_not_over_200_and_is_reported(tmp_path):
    export = tmp_path / "export.csv"
    export.write_text(
        "ticket_id,created_at,status,priority,category,assigned_to,"
        "customer_email,labels,refund_amount\n"
        "TCK-1,2026-10-05 13:05,open,normal,Billing,riya,a@example.com,,lots\n"
        "TCK-2,2026-10-05 13:05,open,normal,Billing,riya,a@example.com,,\n"
        "TCK-3,2026-10-05 13:05,open,normal,Billing,riya,a@example.com,,200\n"
        "TCK-4,2026-10-05 13:05,open,normal,Billing,riya,a@example.com,,200.01\n",
        encoding="utf-8",
    )
    tracker = tmp_path / "tracker.csv"
    tracker.write_text("ticket_id,requested_by,approver,requested_at,decision,decided_at,notes\n")
    service = EscalationService(export, tracker, tmp_path / "decisions.csv")

    body = service.dashboard()

    assert body["attention"]["refund_over_200"] == 1
    assert [t["ticket_id"] for t in body["tickets"] if t["indicators"]] == ["TCK-4"]
    assert any(
        i["ticket_id"] == "TCK-1" and "refund_amount" in i["problem"] for i in service.issues
    )
    assert not any(i["ticket_id"] == "TCK-2" for i in service.issues)


# Approval batch and email ---------------------------------------------------


def test_batch_on_sample_data_is_oldest_first_and_skips_decided(service):
    batch = service.approval_batch()

    assert [(t["ticket_id"], t["approval_stage"]) for t in batch] == [
        ("TCK-5007", "awaiting_decision"),
        ("TCK-5070", "not_requested"),
        ("TCK-5110", "not_requested"),
        ("TCK-5050", "awaiting_decision"),
    ]


def test_batch_matches_current_logs_where_tck_5070_was_accepted(paths):
    # data/ logs currently hold a request and an Accept for TCK-5070.
    paths["requests"].write_text(
        "ticket_id,requested_by,approver,requested_at\nTCK-5070,Lia,Joyce,2026-10-28 23:39\n",
        encoding="utf-8",
    )
    paths["decisions"].write_text(
        "ticket_id,decision,decided_by,decided_at\nTCK-5070,Accept,Joyce,2026-10-28 23:42\n",
        encoding="utf-8",
    )
    batch = make_service(paths).approval_batch()

    assert [t["ticket_id"] for t in batch] == ["TCK-5007", "TCK-5110", "TCK-5050"]


def test_dashboard_batch_reports_fields_saved(client):
    batch = client.get("/dashboard").json()["approval_batch"]

    assert batch["count"] == 4
    assert batch["fields_saved"] == 32


def test_email_preview_format(client, paths):
    body = client.get("/approvals/batch/preview").json()

    assert body["to"] == "Mara"
    assert body["from"] == "Riya"
    assert body["subject"] == "Urgent tickets awaiting your approval (4)"
    assert body["ticket_ids"] == ["TCK-5007", "TCK-5070", "TCK-5110", "TCK-5050"]
    lines = body["body"].splitlines()
    assert lines[0] == "Hi Mara,"
    assert 'APPROVE or REJECT after "Decision:"' in lines[2]
    assert lines[4] == (
        "TCK-5007 | Refunds | urgent | created 05/10/2026 13:05 | in_progress"
        " | assigned to riya | labels escalated | refund 480.00"
    )
    assert lines[5] == "Decision:"
    assert (
        "TCK-5070 | Shipping | urgent | created 11/10/2026 10:49 | in_progress"
        " | assigned to ken | labels escalated | refund —"
    ) in lines
    assert lines[-1] == "Sent by Riya from the Escalation Dashboard."
    assert "@" not in json.dumps(body)
    # Preview writes nothing.
    assert not paths["requests"].exists()


def test_date_and_refund_formatting():
    assert format_created("2026-10-05 13:05") == "05/10/2026 13:05"
    assert format_created("06/10/2026 00:05") == "06/10/2026 00:05"
    assert format_refund(80.0) == "80.00"
    assert format_refund(None) == "—"


# Sending -----------------------------------------------------------------------


def test_send_requests_only_not_requested_tickets(client, sender, paths):
    response = client.post("/approvals/batch/send")

    assert response.status_code == 200
    assert response.json() == {
        "sent": True,
        "ticket_ids": ["TCK-5007", "TCK-5070", "TCK-5110", "TCK-5050"],
        "newly_requested": ["TCK-5070", "TCK-5110"],
        "reminders": ["TCK-5007", "TCK-5050"],
    }
    rows = read_rows(paths["requests"])
    assert [(r["ticket_id"], r["requested_by"], r["approver"]) for r in rows] == [
        ("TCK-5070", "Riya", "Mara"),
        ("TCK-5110", "Riya", "Mara"),
    ]

    [message] = sender.sent
    assert message["To"] == "Mara <mara@example.org>"
    assert message["From"] == "Riya <riya@example.org>"
    assert message["Reply-To"] == "riya@example.org"
    assert message["Subject"] == "Urgent tickets awaiting your approval (4)"
    assert "@example.com" not in message.get_content()

    stages = {
        t["ticket_id"]: t["approval_stage"]
        for t in client.get("/approvals/urgent-open").json()["tickets"]
    }
    assert stages["TCK-5070"] == stages["TCK-5110"] == "awaiting_decision"


def test_second_send_is_reminders_only(client, paths):
    client.post("/approvals/batch/send")
    body = client.post("/approvals/batch/send").json()

    assert body["newly_requested"] == []
    assert body["reminders"] == ["TCK-5007", "TCK-5070", "TCK-5110", "TCK-5050"]
    assert len(read_rows(paths["requests"])) == 2


def test_send_with_empty_batch_is_409_and_sends_nothing(client, sender, service):
    for ticket in service.approval_batch():
        if ticket["approval_stage"] == "not_requested":
            service.request_approval(ticket["ticket_id"], "Riya", "Mara")
        service.record_decision(ticket["ticket_id"], "Accept", "Mara")

    response = client.post("/approvals/batch/send")

    assert response.status_code == 409
    assert "No urgent open tickets" in response.json()["detail"]
    assert sender.sent == []


@pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_PASSWORD"])
def test_send_with_missing_smtp_setting_is_503(client, sender, paths, missing):
    sender.missing = missing

    response = client.post("/approvals/batch/send")

    assert response.status_code == 503
    assert missing in response.json()["detail"]
    assert not paths["requests"].exists()


@pytest.mark.parametrize("missing", ["user_email", "manager_email"])
def test_send_with_missing_address_is_503(client, missing):
    use_settings(**{missing: ""})

    response = client.post("/approvals/batch/send")

    assert response.status_code == 503
    assert f"APPROVAL_{missing.upper()}" in response.json()["detail"]


def test_send_failure_is_502_records_nothing_and_hides_password(
    client, sender, paths, caplog, monkeypatch
):
    import app.main as main

    monkeypatch.setattr(main, "SMTP_PASSWORD", SMTP_SECRET)
    sender.fail = True

    response = client.post("/approvals/batch/send")

    assert response.status_code == 502
    assert response.json()["detail"] == "Approval email could not be sent."
    assert not paths["requests"].exists()
    assert SMTP_SECRET not in response.text
    assert SMTP_SECRET not in caplog.text
    assert "ConnectionRefusedError" in caplog.text


# Reply parsing ----------------------------------------------------------------


EMAIL_BODY = """Hi Mara,

Please write APPROVE or REJECT after "Decision:" for each ticket below, then reply to this email.

TCK-5007 | Refunds | urgent | created 05/10/2026 13:05 | in_progress | assigned to riya | labels escalated | refund 480.00
Decision:

TCK-5050 | Refunds | urgent | created 12/10/2026 06:16 | open | assigned to lia | labels escalated, vip | refund 480.00
Decision:

Sent by Riya from the Escalation Dashboard.
"""


def quoted(text):
    return "\n".join("> " + line for line in text.splitlines())


def test_reply_with_quoted_original_uses_the_written_answers():
    reply = (
        "TCK-5007 Decision: APPROVE\n"
        "TCK-5050 Decision: reject\n\n"
        "On Tue, Riya wrote:\n" + quoted(EMAIL_BODY)
    )

    assert parse_reply(reply) == {"TCK-5007": "accept", "TCK-5050": "reject"}


def test_inline_answers_inside_quoted_email():
    reply = quoted(EMAIL_BODY).replace(
        "> Decision:", "> Decision: Approved", 1
    ).replace("> Decision:\n", "> Decision: DECLINED\n", 1)

    assert parse_reply(reply) == {"TCK-5007": "accept", "TCK-5050": "reject"}


@pytest.mark.parametrize(
    "word, expected",
    [
        ("approve", "accept"),
        ("APPROVED", "accept"),
        ("Accept", "accept"),
        ("ok", "accept"),
        ("Yes", "accept"),
        ("reject", "reject"),
        ("Rejected", "reject"),
        ("decline", "reject"),
        ("NO", "reject"),
    ],
)
def test_decision_words_are_case_insensitive(word, expected):
    assert parse_reply(f"TCK-5007\nDecision: {word}") == {"TCK-5007": expected}


@pytest.mark.parametrize(
    "text",
    ["see note", "Notes: chased", "nobody knows", "okay-ish", "unapproved", "yesterday"],
)
def test_keywords_match_whole_words_only(text):
    assert parse_reply(f"TCK-5007 Decision: {text}") == {"TCK-5007": "blank"}


def test_blank_and_unclear():
    reply = "TCK-5007 Decision:\nTCK-5050 Decision: approve, no wait, reject\n"

    assert parse_reply(reply) == {"TCK-5007": "blank", "TCK-5050": "unclear"}


def test_disagreeing_occurrences_are_unclear():
    reply = "TCK-5007 approve\nTCK-5050 approve\n> TCK-5007 reject\n> TCK-5050 Decision:\n"

    assert parse_reply(reply) == {"TCK-5007": "unclear", "TCK-5050": "accept"}


def test_text_before_first_ticket_is_ignored():
    assert parse_reply("Yes, all good. No problem.\nTCK-5007 Decision: reject") == {
        "TCK-5007": "reject"
    }


def test_reply_without_ticket_ids_raises():
    with pytest.raises(NoTicketsInReply):
        parse_reply("Approve all of them")


def test_reply_preview_statuses(client, paths):
    client.post("/approvals/batch/send")
    reply = (
        "TCK-5007 Decision: approve\n"
        "TCK-5070 Decision:\n"
        "TCK-5110 Decision: approve reject\n"
        "TCK-5050 Decision: REJECT\n"
        "TCK-9999 Decision: approve\n"
        "TCK-5106 Decision: reject\n"
        "TCK-5084 Decision: approve\n"
    )

    response = client.post("/approvals/reply/preview", json={"reply_text": reply})

    assert response.status_code == 200
    body = response.json()
    assert body["manager"] == "Mara"
    assert {t["ticket_id"]: t["status"] for t in body["tickets"]} == {
        "TCK-5007": "accept",
        "TCK-5070": "blank",
        "TCK-5110": "unclear",
        "TCK-5050": "reject",
        "TCK-9999": "not_found",
        "TCK-5106": "not_awaiting",  # already accepted in the tracker
        "TCK-5084": "not_awaiting",  # never requested
    }
    assert body["counts"] == {
        "accept": 1,
        "reject": 1,
        "blank": 1,
        "unclear": 1,
        "not_found": 1,
        "not_awaiting": 2,
    }
    assert all(t["reason"] for t in body["tickets"])
    # Preview writes nothing.
    assert not paths["decisions"].exists()


def test_reply_without_ids_is_422(client):
    response = client.post("/approvals/reply/preview", json={"reply_text": "Approve all"})

    assert response.status_code == 422
    assert "ticket IDs" in response.json()["detail"]


@pytest.mark.parametrize("text", ["", "x" * 50_001])
def test_reply_length_is_validated(client, text):
    assert client.post("/approvals/reply/preview", json={"reply_text": text}).status_code == 422


# Recording ---------------------------------------------------------------------


def test_record_appends_decisions_by_the_manager(client, paths):
    client.post("/approvals/batch/send")
    reply = "TCK-5007 Decision: approve\nTCK-5050 Decision: reject\nTCK-5070 Decision:\n"

    body = client.post("/approvals/reply/record", json={"reply_text": reply}).json()

    assert body["recorded"] == ["TCK-5007", "TCK-5050"]
    assert read_rows(paths["decisions"]) == [
        {"ticket_id": "TCK-5007", "decision": "Accept", "decided_by": "Mara",
         "decided_at": "2026-10-20 09:15"},
        {"ticket_id": "TCK-5050", "decision": "Reject", "decided_by": "Mara",
         "decided_at": "2026-10-20 09:15"},
    ]
    stages = {
        t["ticket_id"]: t["approval_stage"]
        for t in client.get("/approvals/urgent-open").json()["tickets"]
    }
    assert stages["TCK-5007"] == "accepted"
    assert stages["TCK-5050"] == "rejected"
    assert stages["TCK-5070"] == "awaiting_decision"


def test_recording_the_same_reply_twice_adds_nothing(client, paths):
    client.post("/approvals/batch/send")
    reply = "TCK-5007 Decision: approve\n"
    client.post("/approvals/reply/record", json={"reply_text": reply})

    body = client.post("/approvals/reply/record", json={"reply_text": reply}).json()

    assert body["recorded"] == []
    assert body["tickets"][0]["status"] == "not_awaiting"
    assert len(read_rows(paths["decisions"])) == 1


def test_record_ignores_client_supplied_results(client, paths):
    client.post("/approvals/batch/send")
    body = client.post(
        "/approvals/reply/record",
        json={
            "reply_text": "TCK-5007 Decision:",
            "tickets": [{"ticket_id": "TCK-5007", "status": "accept"}],
        },
    ).json()

    assert body["recorded"] == []
    assert not paths["decisions"].exists()


def test_round_trip_leaves_source_csvs_byte_for_byte_unchanged(client, paths):
    before = {
        "export": SAMPLE_EXPORT.read_bytes(),
        "tracker": SAMPLE_TRACKER.read_bytes(),
        "export_copy": paths["export"].read_bytes(),
        "tracker_copy": paths["tracker"].read_bytes(),
    }

    client.post("/approvals/batch/send")
    client.post(
        "/approvals/reply/record",
        json={"reply_text": "TCK-5007 approve\nTCK-5050 reject\n"},
    )

    assert SAMPLE_EXPORT.read_bytes() == before["export"]
    assert SAMPLE_TRACKER.read_bytes() == before["tracker"]
    assert paths["export"].read_bytes() == before["export_copy"]
    assert paths["tracker"].read_bytes() == before["tracker_copy"]


def test_no_endpoint_response_contains_customer_email(client):
    client.post("/approvals/batch/send")
    responses = [
        client.get("/dashboard"),
        client.get("/approvals/config"),
        client.get("/approvals/batch/preview"),
        client.get("/approvals/urgent-open"),
        client.get("/helpdesk/tickets"),
        client.post("/approvals/reply/preview", json={"reply_text": "TCK-5007 approve"}),
    ]

    for response in responses:
        assert response.status_code == 200
        assert not contains_customer_email(response.json()), response.url
