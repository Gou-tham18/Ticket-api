"""Sending through Brevo's HTTPS API, for hosts that block outgoing SMTP."""

import io
import json
import urllib.error
from datetime import datetime

import pytest

import app.approval_email as approval_email
import app.main as main
from app.approval_email import (
    BrevoEmailSender,
    BrevoSettings,
    SmtpEmailSender,
    brevo_payload,
    build_message,
    build_result_message,
)

API_KEY = "xkeysib-test-brevo-key"
EMAIL = {
    "subject": "Urgent tickets awaiting your approval (1)",
    "text_body": "Hi Mara,\n",
    "html_body": "<p>Hi Mara,</p>",
}


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def requests(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(request)
        return FakeResponse()

    monkeypatch.setattr(approval_email.urllib.request, "urlopen", fake_urlopen)
    return sent


def approval_message():
    return build_message(EMAIL, "Riya", "riya@example.org", "Mara", "mara@example.org")


def test_approval_email_payload():
    assert brevo_payload(approval_message()) == {
        "sender": {"email": "riya@example.org", "name": "Riya"},
        "to": [{"email": "mara@example.org", "name": "Mara"}],
        "subject": "Urgent tickets awaiting your approval (1)",
        "textContent": "Hi Mara,\n",
        "htmlContent": "<p>Hi Mara,</p>\n",
        "replyTo": {"email": "riya@example.org"},
    }


def test_result_email_payload_has_the_manager_in_cc():
    message = build_result_message(
        EMAIL, "Riya", "riya@example.org", "Mara", "mara@example.org"
    )

    payload = brevo_payload(message)

    assert payload["to"] == [{"email": "riya@example.org", "name": "Riya"}]
    assert payload["cc"] == [{"email": "mara@example.org", "name": "Mara"}]
    assert "replyTo" not in payload


def test_send_posts_json_with_the_api_key(requests):
    BrevoEmailSender(BrevoSettings(api_key=API_KEY)).send(approval_message())

    (request,) = requests
    assert request.full_url == "https://api.brevo.com/v3/smtp/email"
    assert request.get_method() == "POST"
    assert request.get_header("Api-key") == API_KEY
    assert json.loads(request.data)["to"][0]["email"] == "mara@example.org"


def test_error_response_is_raised_with_brevo_reason(monkeypatch):
    def failing_urlopen(request, timeout):
        body = io.BytesIO(b'{"code":"unauthorized","message":"Sender not valid"}')
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, body)

    monkeypatch.setattr(approval_email.urllib.request, "urlopen", failing_urlopen)

    with pytest.raises(RuntimeError, match="Brevo returned 400: .*Sender not valid") as err:
        BrevoEmailSender(BrevoSettings(api_key=API_KEY)).send(approval_message())
    assert API_KEY not in str(err.value)


def test_missing_key_is_named():
    assert BrevoSettings().missing_setting() == "BREVO_API_KEY"
    assert BrevoSettings(api_key=API_KEY).missing_setting() is None
    assert API_KEY not in repr(BrevoSettings(api_key=API_KEY))


def test_brevo_is_used_when_its_key_is_set(monkeypatch):
    monkeypatch.setattr(main, "BREVO_API_KEY", API_KEY)
    assert isinstance(main.get_email_sender(), BrevoEmailSender)

    monkeypatch.setattr(main, "BREVO_API_KEY", "")
    assert isinstance(main.get_email_sender(), SmtpEmailSender)


def test_brevo_key_is_masked_in_logged_errors(monkeypatch):
    monkeypatch.setattr(main, "BREVO_API_KEY", API_KEY)

    assert API_KEY not in main._safe_error(RuntimeError(f"bad key {API_KEY}"))
