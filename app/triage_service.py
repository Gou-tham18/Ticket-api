
import json
import os
import re
from typing import Literal
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from pydantic import BaseModel, Field, field_validator

from app.retrieval import retrieve_articles


ALLOWED_CATEGORIES = {
    "Billing", "Login", "Shipping",
    "Refunds", "Technical", "Account",
}

ALLOWED_PRIORITIES = {"urgent", "high", "normal", "low"}

CATEGORY_ARTICLES = {
    "Billing": ["KB-003"],
    "Login": ["KB-001"],
    "Shipping": ["KB-004"],
    "Refunds": ["KB-002"],
    "Technical": ["KB-005"],
    "Account": ["KB-006"],
}


class TriageRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=10000)

    @field_validator("subject", "text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field must not be blank.")
        return value


class TriageResult(BaseModel):
    category: Literal[
        "Billing", "Login", "Shipping",
        "Refunds", "Technical", "Account",
    ]
    priority: Literal["urgent", "high", "normal", "low"]
    suggested_reply: str
    article_ids: list[str]


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fallback_category(subject: str, text: str) -> str:
    """Classify tickets using keyword rules."""

    ticket = normalize(f"{subject} {text}")

    rules = [
        ("Refunds", [
            "refund", "reimbursement", "money back",
            "refund not received", "refund status",
        ]),
        ("Shipping", [
            "shipping", "shipment", "delivery", "delivered",
            "tracking", "track", "package", "parcel",
            "order not delivered", "not delivered",
            "late order", "delivery delayed",
            "order not received", "not arrived",
        ]),
        ("Login", [
            "login", "log in", "sign in", "password",
            "locked out", "unable to log in",
            "cannot log in", "forgot password",
        ]),
        ("Billing", [
            "billing", "payment", "charged", "charge",
            "deducted", "invoice", "duplicate transaction",
            "double payment",
        ]),
        ("Account", [
            "account details", "account settings", "profile",
            "change email", "update email", "delete account",
            "account closure",
        ]),
        ("Technical", [
            "error", "crash", "bug", "not loading",
            "application", "technical issue", "website down",
        ]),
    ]

    for category, keywords in rules:
        if any(keyword in ticket for keyword in keywords):
            return category

    return "Technical"


def determine_priority(subject: str, text: str, model_priority) -> str:
    """Apply conservative priority rules to the model's suggestion."""

    ticket = normalize(f"{subject} {text}")

    urgent_phrases = [
        "account compromised",
        "account hacked",
        "unauthorized access",
        "security breach",
        "entire website down",
        "all users affected",
        "business operations stopped",
        "critical system outage",
    ]

    high_phrases = [
        "cannot complete payment",
        "payment failed",
        "unable to access account",
        "business affected",
        "time sensitive",
        "delivery deadline",
        "urgent assistance",
    ]

    if any(phrase in ticket for phrase in urgent_phrases):
        return "urgent"

    if any(phrase in ticket for phrase in high_phrases):
        return "high"

    if model_priority not in ALLOWED_PRIORITIES:
        return "normal"

    # A routine delivery delay alone should not become urgent.
    if model_priority == "urgent":
        return "normal"

    return model_priority


def fallback_reply(category: str, subject: str, text: str) -> str:
    """Generate a category-specific reply without inventing policies."""

    replies = {
        "Billing": (
            "We understand your concern about the payment. "
            "Please share the relevant transaction details through "
            "our support channel so the issue can be reviewed."
        ),
        "Login": (
            "We're sorry you're having trouble accessing your account. "
            "Please try the password reset process. If the issue "
            "continues, our support team can investigate further."
        ),
        "Shipping": (
            "We're sorry your order has not arrived as expected. "
            "Please share your order or tracking details through "
            "our support channel so the delivery status can be checked."
        ),
        "Refunds": (
            "We're sorry your refund has not arrived. "
            "Please provide your order details through our support "
            "channel so the refund status can be reviewed."
        ),
        "Technical": (
            "We're sorry you're experiencing this technical issue. "
            "Please share the steps that caused the problem and any "
            "error message so our support team can investigate."
        ),
        "Account": (
            "We can help with your account request. Please specify "
            "the details you need to update, and our support team "
            "can guide you through the appropriate process."
        ),
    }

    return replies.get(
        category,
        "Thank you for contacting support. Our support team will review your issue.",
    )


def call_model(subject: str, text: str, articles: list[dict]) -> dict:
    """Use local Ollama for priority and suggested reply generation."""

    category = fallback_category(subject, text)

    article_context = [
        {
            "id": article["id"],
            "title": article["title"],
            "content": article["content"],
        }
        for article in articles
    ]

    prompt = f"""
You are a professional customer support assistant.

Return one valid JSON object with these exact keys:
{{
  "category": "{category}",
  "priority": "urgent, high, normal, or low",
  "suggested_reply": "specific reply to this ticket",
  "article_ids": []
}}

The category must be exactly "{category}".

Priority rules:
- urgent: critical outage, account compromise, or severe immediate impact
- high: significant impact or time-sensitive issue
- normal: routine support request
- low: minor question

Do not mark an ordinary delayed delivery urgent.
Address the actual problem in the ticket.
Do not invent policies, guarantees, or delivery timelines.
Use only IDs present in the supplied articles.
If no article is relevant, return an empty article_ids list.
Return JSON only, without Markdown.

Subject: {subject}
Description: {text}

Available articles:
{json.dumps(article_context, ensure_ascii=False)}
"""

    payload = {
        "model": os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    base_url = os.getenv(
        "OLLAMA_BASE_URL",
        "http://127.0.0.1:11434",
    ).rstrip("/")

    request = Request(
        url=f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            response_data = json.loads(
                response.read().decode("utf-8")
            )
    except HTTPError as exc:
        raise RuntimeError(
            f"Ollama returned HTTP {exc.code}."
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. Ensure Ollama is running."
        ) from exc

    content = response_data.get("response")

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The local AI model returned an empty response.")

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "The local AI model returned invalid JSON."
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError("The local AI model returned an invalid JSON object.")

    return result


def triage_ticket(subject: str, text: str) -> TriageResult:
    """Validate input, classify, retrieve articles, and build the result."""

    request_data = TriageRequest(
        subject=subject.strip(),
        text=text.strip(),
    )

    subject = request_data.subject
    text = request_data.text

    category = fallback_category(subject, text)
    articles = retrieve_articles(subject, text)

    # Keep only article IDs that actually exist in retrieved results.
    allowed_ids = {
        article["id"]
        for article in articles
        if isinstance(article, dict) and isinstance(article.get("id"), str)
    }

    # Prefer articles associated with the ticket category.
    preferred_ids = CATEGORY_ARTICLES.get(category, [])
    selected_ids = [
        article_id
        for article_id in preferred_ids
        if article_id in allowed_ids
    ]

    # If the preferred category article was not retrieved, use the
    # relevant articles returned by the retrieval function.
    if not selected_ids:
        selected_ids = [
            article["id"]
            for article in articles
            if isinstance(article, dict)
            and isinstance(article.get("id"), str)
        ]

    # Try the local model. Use a safe category-specific reply if its
    # response is missing or generic.
    result = call_model(subject, text, articles)

    priority = determine_priority(
        subject,
        text,
        result.get("priority"),
    )

    model_reply = result.get("suggested_reply", "")
    generic_replies = {
        "please contact us so we can assist you further",
        "we apologize for the inconvenience please contact us so we can assist you further",
        "thank you for contacting support",
    }

    normalized_reply = normalize(model_reply) if isinstance(model_reply, str) else ""

    if (
        not isinstance(model_reply, str)
        or len(normalized_reply) < 30
        or normalized_reply in generic_replies
    ):
        model_reply = fallback_reply(category, subject, text)

    final_result = {
        "category": category,
        "priority": priority,
        "suggested_reply": model_reply.strip(),
        "article_ids": selected_ids,
    }

    return TriageResult.model_validate(final_result)

