
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.triage_service import triage_ticket

client = TestClient(app)


def test_triage_returns_structured_result():
    mock_result = {
        "category": "Login",
        "priority": "high",
        "suggested_reply": (
            "Please use Forgot password and check your spam folder."
        ),
        "article_ids": ["KB-001"],
    }

    with patch(
        "app.triage_service.call_model",
        return_value=mock_result,
    ):
        response = client.post(
            "/triage",
            json={
                "subject": "Cannot reset password",
                "text": "The reset email never arrived.",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "Login"
    assert data["priority"] == "high"
    assert data["article_ids"] == ["KB-001"]


def test_triage_rejects_blank_subject():
    response = client.post(
        "/triage",
        json={
            "subject": "   ",
            "text": "I cannot sign in.",
        },
    )

    assert response.status_code == 422


def test_triage_rejects_empty_text():
    response = client.post(
        "/triage",
        json={
            "subject": "Login problem",
            "text": "",
        },
    )

    assert response.status_code == 422


def test_triage_handles_model_failure():
    with patch(
        "app.triage_service.call_model",
        side_effect=RuntimeError("Simulated model failure"),
    ):
        response = client.post(
            "/triage",
            json={
                "subject": "Cannot reset password",
                "text": "The reset email never arrived.",
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Ticket triage service failed."


def test_triage_reports_missing_gemini_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    response = client.post(
        "/triage",
        json={
            "subject": "Cannot reset password",
            "text": "The reset email never arrived.",
        },
    )

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_triage_uses_fallback_when_gemini_is_unavailable(monkeypatch):
    from google.genai import errors

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    overloaded = errors.ServerError(
        503,
        {"error": {"code": 503, "status": "UNAVAILABLE"}},
    )

    with patch("app.triage_service.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.side_effect = (
            overloaded
        )
        response = client.post(
            "/triage",
            json={
                "subject": "Cannot reset password",
                "text": "The reset email never arrived.",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "Login"
    assert data["priority"] == "normal"
    assert data["article_ids"] == ["KB-001"]
    assert "password reset" in data["suggested_reply"]


def test_triage_uses_gemini_reply_when_available(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    reply = (
        "Please check your spam folder for the reset email, "
        "then request a new link from the sign-in page."
    )

    with patch("app.triage_service.genai.Client") as mock_client:
        mock_client.return_value.models.generate_content.return_value.text = (
            f'{{"category": "Login", "priority": "high", '
            f'"suggested_reply": "{reply}", "article_ids": ["KB-001"]}}'
        )
        response = client.post(
            "/triage",
            json={
                "subject": "Cannot reset password",
                "text": "The reset email never arrived.",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["priority"] == "high"
    assert data["suggested_reply"] == reply
    assert data["article_ids"] == ["KB-001"]
