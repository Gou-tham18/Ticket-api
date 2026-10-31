"""Approve/Reject buttons: signed links, confirmation page, result email,
reminders, and the dashboard fields that show them.

Every test uses copies of the sample files in tmp_path, a fake clock and a
fake email sender, so nothing touches data/ or opens a network connection.
"""

import csv
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.approval_links import (
    ExpiredLink,
    InvalidLink,
    _encode,
    link_for,
    make_token,
    read_token,
)
from app.escalations import EscalationService
from app.main import (
    ApprovalSettings,
    app,
    day_setting,
    get_approval_settings,
    get_email_sender,
    get_escalation_service,
    link_secret_setting,
    public_base_url_setting,
)

SAMPLE_EXPORT = Path("data/helpdesk_export_sample.csv")
SAMPLE_TRACKER = Path("data/escalation_tracker_sample.csv")

NOW = datetime(2026, 10, 20, 9, 15)
SECRET = "test-link-secret-0123456789abcdefghij"
BASE_URL = "https://approvals.example.org"
SMTP_SECRET = "s3cret-smtp-password"

SETTINGS = ApprovalSettings(
    user_name="Riya",
    user_email="riya@example.org",
    manager_name="Mara",
    manager_email="mara@example.org",
    public_base_url=BASE_URL,
    link_secret=SECRET,
    link_days=7,
)

TOKEN_RE = re.compile(r"token=([A-Za-z0-9_.-]+)")


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    """Stands in for SmtpEmailSender so no network connection is opened."""

    def __init__(self):
        self.fail = False
        self.missing = None
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
    export = tmp_path / "export.csv"
    tracker = tmp_path / "tracker.csv"
    shutil.copyfile(SAMPLE_EXPORT, export)
    shutil.copyfile(SAMPLE_TRACKER, tracker)
    return {
        "export": export,
        "tracker": tracker,
        "decisions": tmp_path / "decisions.csv",
        "requests": tmp_path / "requests.csv",
        "emails": tmp_path / "emails.csv",
    }


@pytest.fixture
def clock():
    return FakeClock(NOW)


def make_service(paths, clock, reminder_days=1):
    return EscalationService(
        paths["export"],
        paths["tracker"],
        paths["decisions"],
        clock=clock,
        request_log_path=paths["requests"],
        email_log_path=paths["emails"],
        fixed_manager="Mara",
        reminder_days=reminder_days,
    )


@pytest.fixture
def service(paths, clock):
    return make_service(paths, clock)


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


def token_for(ticket_id, decision="Accept", expires_at=NOW + timedelta(days=7), secret=SECRET):
    return make_token(ticket_id, decision, expires_at, secret)


def visible_text(page: str) -> str:
    return re.sub(r"<[^>]+>", " ", page)


def batch_ids(service):
    return [(t["ticket_id"], t["send_reason"]) for t in service.approval_batch()]


# 1-3. Links ------------------------------------------------------------------


def test_token_round_trips():
    expires = NOW + timedelta(days=7)
    token = make_token("TCK-5007", "Reject", expires, SECRET)

    claims = read_token(token, SECRET, NOW)

    assert (claims.ticket_id, claims.decision, claims.expires_at) == ("TCK-5007", "Reject", expires)
    # Short, URL-safe, unpadded.
    assert re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
    assert len(token) < 100
    assert link_for(BASE_URL, token) == f"{BASE_URL}/approvals/respond?token={token}"


def _expiry(days: int) -> int:
    return int((NOW + timedelta(days=days)).timestamp())


def _resigned_payload(token: str, payload: str) -> str:
    # Swap in another payload but keep the original signature.
    return f"{_encode(payload.encode())}.{token.split('.')[1]}"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda t: _resigned_payload(t, f"TCK-5050|A|{_expiry(7)}"),
        lambda t: _resigned_payload(t, f"TCK-5007|R|{_expiry(7)}"),
        lambda t: _resigned_payload(t, f"TCK-5007|A|{_expiry(70)}"),
        lambda t: token_for("TCK-5007", secret="another-secret-0123456789abcdefghij"),
        lambda t: t[:-2],
        lambda t: t + "<script>",
        lambda t: "",
        lambda t: "not-a-token",
        lambda t: "x" * 1000,
    ],
    ids=["ticket", "decision", "expiry", "secret", "truncated", "junk", "empty", "garbage", "long"],
)
def test_changed_or_foreign_tokens_are_invalid(tamper):
    token = token_for("TCK-5007", "Accept")

    with pytest.raises(InvalidLink):
        read_token(tamper(token), SECRET, NOW)


def test_token_past_expiry_is_expired():
    expires = NOW + timedelta(days=7)
    token = token_for("TCK-5007", expires_at=expires)

    assert read_token(token, SECRET, expires).ticket_id == "TCK-5007"
    with pytest.raises(ExpiredLink) as caught:
        read_token(token, SECRET, expires + timedelta(seconds=1))
    assert caught.value.claims.ticket_id == "TCK-5007"


# 4-5. Confirmation page (GET) -------------------------------------------------


def test_get_never_records(client, paths):
    for decision in ("Accept", "Reject"):
        for _ in range(3):
            response = client.get(f"/approvals/respond?token={token_for('TCK-5007', decision)}")
            assert response.status_code == 200

    assert not paths["decisions"].exists()
    assert client.get("/helpdesk/tickets/TCK-5007").json()["escalation"]["state"] == "pending"


@pytest.mark.parametrize("decision, verb", [("Accept", "Approve"), ("Reject", "Reject")])
def test_get_valid_link_shows_ticket_and_confirm(client, decision, verb):
    token = token_for("TCK-5007", decision)

    response = client.get(f"/approvals/respond?token={token}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert f"<h1>{verb} TCK-5007?</h1>" in page
    for value in ("Refunds", "urgent", "05/10/2026 13:05", "in_progress", "riya", "escalated", "480.00"):
        assert value in page
    assert f'<form method="post" action="/approvals/respond?token={token}">' in page
    assert ">Confirm</button>" in page
    assert "close this page to do nothing" in page
    assert "<script" not in page.lower()
    assert 'name="viewport"' in page


def test_get_already_decided(client, service):
    service.record_decision("TCK-5007", "Accept", "Ajith")

    response = client.get(f"/approvals/respond?token={token_for('TCK-5007', 'Reject')}")

    assert response.status_code == 409
    assert "TCK-5007 was already approved by Ajith on 20/10/2026 09:15." in response.text
    assert "<form" not in response.text


def test_get_expired(client, clock):
    token = token_for("TCK-5007")
    clock.advance(days=8)

    response = client.get(f"/approvals/respond?token={token}")

    assert response.status_code == 410
    assert (
        "This link has expired. The ticket will be sent to you again as a reminder."
        in response.text
    )
    assert "<form" not in response.text


def test_expired_link_for_a_decided_ticket_says_already_decided(client, service, clock):
    token = token_for("TCK-5007")
    service.record_decision("TCK-5007", "Reject", "Mara")
    clock.advance(days=8)

    response = client.get(f"/approvals/respond?token={token}")

    assert response.status_code == 409
    assert "TCK-5007 was already rejected by Mara" in response.text


@pytest.mark.parametrize("query", ["?token=abc.def", "?token=", "", "?token=%3Cb%3E.x"])
def test_get_invalid_link(client, query):
    response = client.get(f"/approvals/respond{query}")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert (
        "This link is not valid. Please use the buttons in the latest approval email."
        in response.text
    )


@pytest.mark.parametrize(
    "ticket_id, sentence",
    [
        ("TCK-9999", "TCK-9999 is not in the Help Desk export, so no decision is needed."),
        ("TCK-5043", "TCK-5043 is no longer an urgent open ticket, so no decision is needed."),
        ("TCK-5110", "TCK-5110 is not waiting for approval, so no decision is needed."),
    ],
)
def test_get_ticket_needing_no_decision(client, ticket_id, sentence):
    response = client.get(f"/approvals/respond?token={token_for(ticket_id)}")

    assert response.status_code == 200
    assert sentence in response.text
    assert "<form" not in response.text


@pytest.mark.parametrize("missing", ["link_secret", "manager_name"])
def test_get_not_configured(client, missing):
    use_settings(**{missing: ""})

    response = client.get(f"/approvals/respond?token={token_for('TCK-5007')}")

    assert response.status_code == 503
    assert "Approval links are not set up on the server." in response.text


# 6-8. Confirm (POST) ----------------------------------------------------------


def test_post_records_as_the_manager(client, paths):
    response = client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    assert response.status_code == 200
    assert (
        "Recorded: TCK-5007 approved by Mara on 20/10/2026 09:15. You can close this page."
        in response.text
    )
    assert read_rows(paths["decisions"]) == [
        {"ticket_id": "TCK-5007", "decision": "Accept", "decided_by": "Mara",
         "decided_at": "2026-10-20 09:15"},
    ]
    escalation = client.get("/helpdesk/tickets/TCK-5007").json()["escalation"]
    assert escalation["state"] == "accepted"


def test_post_reject(client, paths):
    response = client.post(f"/approvals/respond?token={token_for('TCK-5050', 'Reject')}")

    assert "Recorded: TCK-5050 rejected by Mara" in response.text
    assert read_rows(paths["decisions"])[0]["decision"] == "Reject"


@pytest.mark.parametrize("second", ["Accept", "Reject"])
def test_second_post_or_other_button_records_nothing(client, paths, second):
    client.post(f"/approvals/respond?token={token_for('TCK-5007', 'Accept')}")

    response = client.post(f"/approvals/respond?token={token_for('TCK-5007', second)}")

    assert response.status_code == 409
    assert "TCK-5007 was already approved by Mara on 20/10/2026 09:15." in response.text
    assert len(read_rows(paths["decisions"])) == 1


def test_expired_or_invalid_post_records_nothing(client, paths, clock, sender):
    expired = token_for("TCK-5007")
    clock.advance(days=7, minutes=1)

    assert client.post(f"/approvals/respond?token={expired}").status_code == 410
    assert client.post("/approvals/respond?token=abc.def").status_code == 400
    assert client.post("/approvals/respond").status_code == 400
    # Valid link, but the ticket was never sent for approval.
    not_requested = token_for("TCK-5110", expires_at=clock() + timedelta(days=7))
    assert client.post(f"/approvals/respond?token={not_requested}").status_code == 409
    assert not paths["decisions"].exists()
    assert sender.sent == []


def test_post_with_locked_decision_log_shows_a_page_and_records_nothing(client, paths, sender):
    paths["decisions"].mkdir()  # like a file open in Excel

    response = client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "could not be saved" in response.text
    assert "decisions.csv" not in response.text
    assert sender.sent == []


# 9-10. Page safety and headers ----------------------------------------------


def test_pages_hide_token_secret_and_addresses(client, service):
    accept, reject = token_for("TCK-5007", "Accept"), token_for("TCK-5007", "Reject")
    pages = {
        "confirm": client.get(f"/approvals/respond?token={accept}").text,
        "invalid": client.get("/approvals/respond?token=abc.def").text,
        "recorded": client.post(f"/approvals/respond?token={accept}").text,
        "decided": client.get(f"/approvals/respond?token={reject}").text,
    }

    for name, page in pages.items():
        assert SECRET not in page, name
        assert "@" not in page, name
        assert "customer_email" not in page, name
        assert "omar.ali" not in page, name
        assert ".csv" not in page, name
        assert accept not in visible_text(page), name
        assert reject not in page, name
    # The token is only in the confirm form's action, never shown.
    assert pages["confirm"].count(accept) == 1
    assert accept not in pages["recorded"]


def test_pages_escape_values(client, paths):
    text = paths["export"].read_text(encoding="utf-8")
    paths["export"].write_text(
        text.replace(
            "TCK-5007,2026-10-05 13:05,in_progress,urgent,Refunds,riya,",
            'TCK-5007,2026-10-05 13:05,in_progress,urgent,<i>Refunds</i>,<script>alert(1)</script>,',
        ),
        encoding="utf-8",
    )
    app.dependency_overrides[get_escalation_service] = lambda: make_service(paths, FakeClock(NOW))
    use_settings(manager_name='Mara "<b>"')

    confirm = client.get(f"/approvals/respond?token={token_for('TCK-5007')}").text
    recorded = client.post(f"/approvals/respond?token={token_for('TCK-5007')}").text

    assert "<script>alert(1)</script>" not in confirm
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in confirm
    assert "&lt;i&gt;Refunds&lt;/i&gt;" in confirm
    assert "<b>" not in recorded
    assert "&lt;b&gt;" in recorded


@pytest.mark.parametrize(
    "method, query",
    [
        ("get", "valid"),
        ("get", "?token=bad.token"),
        ("post", "valid"),
        ("post", "?token=bad.token"),
    ],
)
def test_respond_headers(client, method, query):
    if query == "valid":
        query = f"?token={token_for('TCK-5007')}"

    response = getattr(client, method)(f"/approvals/respond{query}")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-robots-tag"] == "noindex"


def test_respond_page_for_a_missing_export_is_html(client, paths):
    import app.main as main_module

    app.dependency_overrides.pop(get_escalation_service)
    original = main_module.HELPDESK_EXPORT_PATH
    main_module.HELPDESK_EXPORT_PATH = str(paths["export"].with_name("gone.csv"))
    main_module._escalation_service = None
    try:
        response = client.get(f"/approvals/respond?token={token_for('TCK-5007')}")
    finally:
        main_module.HELPDESK_EXPORT_PATH = original
        main_module._escalation_service = None

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "gone.csv" not in response.text
    assert response.headers["cache-control"] == "no-store"


# 11-12. Result email ----------------------------------------------------------


def test_result_email_goes_to_user_with_manager_in_cc(client, sender):
    client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    [message] = sender.sent
    assert message["From"] == "Riya <riya@example.org>"
    assert message["To"] == "Riya <riya@example.org>"
    assert message["Cc"] == "Mara <mara@example.org>"
    assert message["Subject"] == "TCK-5007 approved by Mara"
    assert message.get_content_type() == "multipart/alternative"
    text = message.get_body(("plain",)).get_content()
    html_part = message.get_body(("html",)).get_content()
    assert "Mara approved TCK-5007 on 20/10/2026 at 09:15." in text
    assert "TCK-5007 | Refunds | urgent | created 05/10/2026 13:05" in text
    assert "Mara approved TCK-5007 on 20/10/2026 at 09:15." in html_part
    assert "omar.ali" not in text + html_part


def test_result_email_subject_for_reject(client, sender):
    client.post(f"/approvals/respond?token={token_for('TCK-5050', 'Reject')}")

    assert sender.sent[0]["Subject"] == "TCK-5050 rejected by Mara"


def test_failing_result_email_keeps_the_decision(client, sender, paths, caplog, monkeypatch):
    monkeypatch.setattr(main, "SMTP_PASSWORD", SMTP_SECRET)
    sender.fail = True

    with caplog.at_level(logging.WARNING):
        response = client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    assert response.status_code == 200
    assert "Recorded: TCK-5007 approved by Mara" in response.text
    assert (
        "Your decision is saved, but the confirmation email could not be sent."
        in response.text
    )
    assert read_rows(paths["decisions"])[0]["ticket_id"] == "TCK-5007"
    assert "ConnectionRefusedError" in caplog.text
    assert SMTP_SECRET not in caplog.text
    assert SECRET not in caplog.text


def test_result_email_not_configured_still_records(client, sender, paths):
    sender.missing = "SMTP_HOST"

    response = client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    assert response.status_code == 200
    assert "confirmation email could not be sent" in response.text
    assert len(read_rows(paths["decisions"])) == 1


# 13-17. Sending ----------------------------------------------------------------


def _parts(message):
    return (
        message.get_body(("plain",)).get_content(),
        message.get_body(("html",)).get_content(),
    )


def test_email_is_multipart_with_signed_links_per_ticket(client, sender):
    client.post("/approvals/batch/send")

    [message] = sender.sent
    assert message.get_content_type() == "multipart/alternative"
    assert message["To"] == "Mara <mara@example.org>"
    assert message["From"] == "Riya <riya@example.org>"
    assert message["Reply-To"] == "riya@example.org"
    text, html_part = _parts(message)
    for body in (text, html_part):
        claims = [read_token(t, SECRET, NOW) for t in TOKEN_RE.findall(body)]
        assert [(c.ticket_id, c.decision) for c in claims] == [
            (ticket_id, decision)
            for ticket_id in ("TCK-5070", "TCK-5110", "TCK-5007", "TCK-5050")
            for decision in ("Accept", "Reject")
        ]
        assert {c.expires_at for c in claims} == {NOW + timedelta(days=7)}
        assert body.count(f"{BASE_URL}/approvals/respond?token=") == 8
    assert ">Approve</a>" in html_part and ">Reject</a>" in html_part
    assert "#15803d" in html_part and "#b91c1c" in html_part
    assert "<script" not in html_part.lower()
    assert "Hi Mara," in html_part
    assert "Replies to this email are not recorded." in html_part
    assert "Links work until 27/10/2026. Sent by Riya from the Escalation Dashboard." in html_part


def test_email_has_reminder_lines_and_no_decision_lines(client, sender):
    client.post("/approvals/batch/send")

    text, html_part = _parts(sender.sent[0])
    assert sender.sent[0]["Subject"] == (
        "Urgent tickets awaiting your approval (4, including 2 reminders)"
    )
    for body in (text, html_part):
        assert "Reminder: first sent 05/10/2026, waiting 14 days" in body
        assert "Reminder: first sent 12/10/2026, waiting 7 days" in body
        assert body.count("Reminder:") == 2
        assert "Decision:" not in body
        assert "write APPROVE" not in body
        assert "@example.com" not in body
    lines = text.splitlines()
    index = lines.index(next(line for line in lines if line.startswith("TCK-5007 |")))
    assert lines[index + 1].startswith("Reminder:")
    assert lines[index + 2].startswith("Approve: ")
    assert lines[index + 3].startswith("Reject: ")


def test_html_body_escapes_values(client, sender):
    use_settings(manager_name="Mara <b>", user_name="Riya & co")

    preview = client.get("/approvals/batch/preview").json()

    assert "Hi Mara &lt;b&gt;," in preview["html_body"]
    assert "Riya &amp; co" in preview["html_body"]


def test_preview_returns_text_and_html_with_the_same_links(client, paths):
    body = client.get("/approvals/batch/preview").json()

    assert body["body"] == body["text_body"]
    assert TOKEN_RE.findall(body["text_body"]) == TOKEN_RE.findall(body["html_body"])
    assert len(TOKEN_RE.findall(body["text_body"])) == 8
    assert not paths["requests"].exists()
    assert not paths["emails"].exists()


@pytest.mark.parametrize(
    "setting, name",
    [("public_base_url", "PUBLIC_BASE_URL"), ("link_secret", "APPROVAL_LINK_SECRET")],
)
@pytest.mark.parametrize("method, path", [("post", "/approvals/batch/send"), ("get", "/approvals/batch/preview")])
def test_missing_link_setting_is_503(client, sender, paths, setting, name, method, path):
    use_settings(**{setting: ""})

    response = getattr(client, method)(path)

    assert response.status_code == 503
    assert name in response.json()["detail"]
    assert SECRET not in response.text
    assert sender.sent == []
    assert not paths["emails"].exists()


def test_failed_send_writes_nothing(client, sender, paths):
    sender.fail = True

    response = client.post("/approvals/batch/send")

    assert response.status_code == 502
    assert not paths["requests"].exists()
    assert not paths["emails"].exists()
    assert batch_ids(make_service(paths, FakeClock(NOW)))[:2] == [
        ("TCK-5070", "new"), ("TCK-5110", "new"),
    ]


def test_successful_send_writes_email_log(client, paths):
    response = client.post("/approvals/batch/send")

    assert response.status_code == 200
    assert response.json()["next_reminder_due_at"] == "2026-10-21 09:15"
    assert read_rows(paths["emails"]) == [
        {"ticket_id": "TCK-5070", "sent_at": "2026-10-20 09:15", "kind": "new"},
        {"ticket_id": "TCK-5110", "sent_at": "2026-10-20 09:15", "kind": "new"},
        {"ticket_id": "TCK-5007", "sent_at": "2026-10-20 09:15", "kind": "reminder"},
        {"ticket_id": "TCK-5050", "sent_at": "2026-10-20 09:15", "kind": "reminder"},
    ]
    # New tickets are still requested the existing way.
    assert [r["ticket_id"] for r in read_rows(paths["requests"])] == ["TCK-5070", "TCK-5110"]


def test_locked_email_log_stops_the_send(client, sender, paths):
    paths["emails"].mkdir()

    response = client.post("/approvals/batch/send")

    assert response.status_code == 503
    assert "emails.csv" in response.json()["detail"]
    assert sender.sent == []
    assert not paths["requests"].exists()


def test_email_log_failure_after_send_is_a_clear_error_with_no_partial_rows(
    client, service, sender, paths, monkeypatch
):
    import app.escalations as escalations

    def locked(path, fieldnames, rows):
        if path == paths["emails"]:
            raise escalations.LogWriteError(path.name)
        return original(path, fieldnames, rows)

    original = escalations._append_csv_rows
    monkeypatch.setattr(escalations, "_append_csv_rows", locked)

    response = client.post("/approvals/batch/send")

    assert response.status_code == 503
    assert "was sent, but emails.csv could not be saved" in response.json()["detail"]
    assert not paths["emails"].exists()


def test_nothing_to_send_messages(client, service, clock):
    client.post("/approvals/batch/send")

    detail = client.post("/approvals/batch/send").json()["detail"]
    assert detail == (
        "Nothing to send yet. 4 tickets are waiting for the manager's reply; "
        "the next reminder is due 21/10/2026."
    )

    for ticket_id in ("TCK-5070", "TCK-5110", "TCK-5007", "TCK-5050"):
        service.record_decision(ticket_id, "Accept", "Mara")
    response = client.post("/approvals/batch/send")
    assert response.status_code == 409
    assert response.json()["detail"] == "No urgent open tickets need a decision."


# 18-22. Reminders --------------------------------------------------------------


def test_reminder_is_due_after_exactly_one_day(client, service, clock):
    client.post("/approvals/batch/send")

    clock.advance(hours=23, minutes=59)
    assert service.approval_batch() == []
    assert len(service.waiting_for_reply()) == 4

    clock.advance(minutes=1)
    # All reminders now, so simply oldest first by created_at.
    assert batch_ids(service) == [
        ("TCK-5007", "reminder"),
        ("TCK-5070", "reminder"),
        ("TCK-5110", "reminder"),
        ("TCK-5050", "reminder"),
    ]
    assert service.waiting_for_reply() == []


def test_second_send_writes_reminder_rows_and_waits_another_day(client, service, clock, paths):
    client.post("/approvals/batch/send")
    clock.advance(days=1)

    body = client.post("/approvals/batch/send").json()

    assert body["newly_requested"] == []
    assert body["reminders"] == ["TCK-5007", "TCK-5070", "TCK-5110", "TCK-5050"]
    rows = read_rows(paths["emails"])
    assert [(r["sent_at"], r["kind"]) for r in rows[4:]] == [("2026-10-21 09:15", "reminder")] * 4
    assert len(read_rows(paths["requests"])) == 2

    clock.advance(hours=23, minutes=59)
    assert service.approval_batch() == []
    clock.advance(minutes=1)
    assert len(service.approval_batch()) == 4


def test_email_log_survives_a_reload(client, paths, clock):
    client.post("/approvals/batch/send")
    clock.advance(hours=12)

    reloaded = make_service(paths, clock)

    assert reloaded.approval_batch() == []
    assert reloaded.waiting_for_reply()[0]["last_emailed_at"] == "2026-10-20 09:15"


def test_tracker_only_awaiting_ticket_with_old_request_is_ready_now(service):
    batch = {t["ticket_id"]: t for t in service.approval_batch()}

    ticket = batch["TCK-5007"]
    assert ticket["send_reason"] == "reminder"
    assert ticket["last_emailed_at"] == "2026-10-05 23:05"
    assert ticket["days_waiting"] == 14
    new = batch["TCK-5110"]
    assert (new["send_reason"], new["last_emailed_at"], new["days_waiting"]) == ("new", None, None)


def test_recent_tracker_request_waits(paths, clock):
    paths["requests"].write_text(
        "ticket_id,requested_by,approver,requested_at\nTCK-5110,Riya,Mara,2026-10-20 08:00\n",
        encoding="utf-8",
    )
    service = make_service(paths, clock)

    assert "TCK-5110" not in [t for t, _ in batch_ids(service)]
    assert service.waiting_for_reply() == [
        {
            "ticket_id": "TCK-5110",
            "category": "Billing",
            "summary_line": service.ticket_summary("TCK-5110")["summary_line"],
            "last_emailed_at": "2026-10-20 08:00",
            "reminder_due_at": "2026-10-21 08:00",
        }
    ]


def test_decided_tickets_never_come_back(client, service, clock):
    client.post("/approvals/batch/send")
    service.record_decision("TCK-5070", "Accept", "Mara")
    service.record_decision("TCK-5110", "Reject", "Mara")
    service.record_decision("TCK-5007", "Accept", "Mara")
    service.record_decision("TCK-5050", "Reject", "Mara")

    for _ in range(30):
        clock.advance(days=1)
        assert service.approval_batch() == []
        assert service.waiting_for_reply() == []
    # Tracker decisions (TCK-5106 OK, TCK-5036 Approved) never appear either.
    assert client.get("/dashboard").json()["approval_batch"]["count"] == 0


def test_reminder_days_setting_of_three(paths, clock):
    service = make_service(paths, clock, reminder_days=3)
    batch = service.approval_batch()
    for ticket in batch:
        if ticket["send_reason"] == "new":
            service.request_approval(ticket["ticket_id"], "Riya", "Mara")
    service.log_emails(batch, clock())

    clock.advance(days=2, hours=23, minutes=59)
    assert service.approval_batch() == []
    assert service.waiting_for_reply()[0]["reminder_due_at"] == "2026-10-23 09:15"
    clock.advance(minutes=1)
    assert len(service.approval_batch()) == 4


@pytest.mark.parametrize("raw", ["0", "31", "abc", "1.5", "-2", "1e3"])
def test_invalid_day_settings_fall_back_with_a_warning(raw, caplog):
    with caplog.at_level(logging.WARNING):
        assert day_setting("APPROVAL_REMINDER_DAYS", raw, 1) == 1

    assert "APPROVAL_REMINDER_DAYS must be a whole number from 1 to 30" in caplog.text


def test_invalid_day_setting_value_is_not_logged(caplog):
    with caplog.at_level(logging.WARNING):
        day_setting("APPROVAL_LINK_DAYS", "seven-ish", 7)

    assert "seven-ish" not in caplog.text


@pytest.mark.parametrize("raw, expected", [("3", 3), (" 30 ", 30), ("1", 1), ("", 7), (None, 7)])
def test_valid_day_settings(raw, expected):
    assert day_setting("APPROVAL_LINK_DAYS", raw, 7) == expected


def test_public_base_url_and_secret_settings(caplog):
    assert public_base_url_setting(" https://name.ngrok-free.dev/ ") == "https://name.ngrok-free.dev"
    assert public_base_url_setting("http://localhost:8000//") == "http://localhost:8000"
    with caplog.at_level(logging.WARNING):
        assert public_base_url_setting("name.ngrok-free.dev") == ""
        assert public_base_url_setting("ftp://x") == ""
        assert link_secret_setting("too-short") == ""
    assert link_secret_setting("x" * 32) == "x" * 32
    assert "too-short" not in caplog.text
    assert "APPROVAL_LINK_SECRET must be at least 32 characters" in caplog.text


def test_link_days_setting_sets_expiry(client, sender):
    use_settings(link_days=2)

    client.post("/approvals/batch/send")

    text, _ = _parts(sender.sent[0])
    expiries = {read_token(t, SECRET, NOW).expires_at for t in TOKEN_RE.findall(text)}
    assert expiries == {NOW + timedelta(days=2)}
    assert "Links work until 22/10/2026." in text


# 23-26. Dashboard --------------------------------------------------------------


def test_dashboard_new_fields(client, clock):
    client.post("/approvals/batch/send")
    client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    body = client.get("/dashboard").json()

    assert body["reminder_days"] == 1
    assert body["link_days"] == 7
    assert body["next_reminder_due_at"] == "2026-10-21 09:15"
    assert [t["ticket_id"] for t in body["waiting_for_reply"]] == ["TCK-5050", "TCK-5070", "TCK-5110"]
    assert set(body["waiting_for_reply"][0]) == {
        "ticket_id", "category", "summary_line", "last_emailed_at", "reminder_due_at",
    }
    tickets = {t["ticket_id"]: t for t in body["tickets"]}
    assert {k: tickets["TCK-5007"][k] for k in ("decision", "decided_by", "decided_at", "decision_source", "approval_stage")} == {
        "decision": "Accept",
        "decided_by": "Mara",
        "decided_at": "2026-10-20 09:15",
        "decision_source": "prototype",
        "approval_stage": "accepted",
    }
    # Tracker decision on a resolved ticket.
    assert tickets["TCK-5039"]["approval_stage"] == "rejected"
    assert tickets["TCK-5039"]["decision_source"] == "tracker"
    assert body["recent_decisions"] == [
        {"ticket_id": "TCK-5007", "category": "Refunds", "decision": "Accept",
         "decided_by": "Mara", "decided_at": "2026-10-20 09:15"},
    ]
    assert body["approval_batch"]["count"] == 0

    clock.advance(days=1)
    batch = client.get("/dashboard").json()["approval_batch"]["tickets"]
    assert batch[0]["send_reason"] == "reminder"
    assert batch[0]["last_emailed_at"] == "2026-10-20 09:15"
    assert isinstance(batch[0]["days_waiting"], int)


def test_recent_decisions_newest_first_capped_at_20(paths, clock):
    with open(paths["export"], newline="", encoding="utf-8-sig") as file:
        ids = [row["ticket_id"] for row in csv.DictReader(file)][:25]
    lines = ["ticket_id,decision,decided_by,decided_at"] + [
        f"{ticket_id},{'Accept' if i % 2 else 'Reject'},Mara,2026-10-{i + 1:02d} 10:00"
        for i, ticket_id in enumerate(ids)
    ]
    paths["decisions"].write_text("\n".join(lines) + "\n", encoding="utf-8")

    decisions = make_service(paths, clock).dashboard()["recent_decisions"]

    assert len(decisions) == 20
    assert [d["ticket_id"] for d in decisions] == list(reversed(ids))[:20]
    assert decisions[0]["decided_at"] == "2026-10-25 10:00"


def test_open_tickets_come_first_oldest_first(tmp_path, clock):
    export = tmp_path / "export.csv"
    export.write_text(
        "ticket_id,created_at,status,priority,category,assigned_to,"
        "customer_email,labels,refund_amount\n"
        "TCK-1,2026-10-05 13:05,resolved,normal,Billing,riya,a@example.com,,\n"
        "TCK-2,2026-10-09 13:05,open,normal,Billing,riya,a@example.com,,\n"
        "TCK-3,2026-10-01 13:05,closed,normal,Billing,riya,a@example.com,,\n"
        "TCK-4,2026-10-03 13:05,in_progress,urgent,Billing,riya,a@example.com,,\n"
        "TCK-5,06/10/2026 13:05,open,normal,Billing,riya,a@example.com,,\n",
        encoding="utf-8",
    )
    tracker = tmp_path / "tracker.csv"
    tracker.write_text("ticket_id,requested_by,approver,requested_at,decision,decided_at,notes\n")
    service = EscalationService(export, tracker, tmp_path / "decisions.csv", clock=clock)

    body = service.dashboard()

    assert [t["ticket_id"] for t in body["tickets"]] == ["TCK-4", "TCK-5", "TCK-2", "TCK-3", "TCK-1"]
    assert (body["total_tickets"], body["open_tickets"]) == (5, 3)
    assert body["attention"]["urgent_open"] == 1


def test_dashboard_never_contains_customer_email(client):
    client.post("/approvals/batch/send")
    client.post(f"/approvals/respond?token={token_for('TCK-5007')}")

    text = client.get("/dashboard").text

    assert "customer_email" not in text
    assert "@example.com" not in text
    assert SECRET not in text


# 27-28. Config --------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes, buttons, missing",
    [
        ({}, True, []),
        ({"public_base_url": ""}, False, ["PUBLIC_BASE_URL"]),
        ({"link_secret": ""}, False, ["APPROVAL_LINK_SECRET"]),
        ({"public_base_url": "", "link_secret": ""}, False, ["PUBLIC_BASE_URL", "APPROVAL_LINK_SECRET"]),
    ],
)
def test_buttons_configured(client, changes, buttons, missing):
    use_settings(**changes)

    body = client.get("/approvals/config").json()

    assert body["buttons_configured"] is buttons
    assert body["buttons_missing"] == missing
    assert body["email_configured"] is buttons
    assert body["configured"] is True


def test_config_leaks_no_values(client):
    text = client.get("/approvals/config").text

    for value in (SECRET, BASE_URL, "approvals.example.org", "@", "example.org"):
        assert value not in text


def test_settings_repr_hides_the_secret():
    assert SECRET not in repr(SETTINGS)


def test_respond_route_is_not_swallowed_by_the_static_mount(client):
    response = client.get("/approvals/respond?token=x.y")

    assert response.status_code == 400
    assert "This link is not valid" in response.text


def test_round_trip_never_touches_data_folder(client, clock):
    real_log = Path(main.APPROVAL_EMAIL_LOG_PATH)
    log_before = real_log.read_bytes() if real_log.exists() else None
    before = (SAMPLE_EXPORT.read_bytes(), SAMPLE_TRACKER.read_bytes())

    client.post("/approvals/batch/send")
    client.post(f"/approvals/respond?token={token_for('TCK-5007')}")
    clock.advance(days=1)
    client.post("/approvals/batch/send")

    assert (SAMPLE_EXPORT.read_bytes(), SAMPLE_TRACKER.read_bytes()) == before
    assert (real_log.read_bytes() if real_log.exists() else None) == log_before
