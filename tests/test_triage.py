
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
