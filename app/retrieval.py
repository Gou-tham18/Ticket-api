
import re
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "kb"

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "i",
    "my", "me", "we", "our", "you", "your", "it", "this",
    "that", "to", "of", "for", "in", "on", "at", "and",
    "or", "but", "with", "from", "can", "could", "would",
    "please", "help", "have", "has", "had", "do", "does",
    "did", "be", "been", "will", "not", "yet", "still",
    "about", "when", "where", "what", "how", "need",
}

TOPIC_TERMS = {
    "KB-001": {
        "password", "login", "signin", "sign", "forgot",
        "reset", "locked", "unlock", "credentials", "email",
    },
    "KB-002": {
        "refund", "refunds", "moneyback", "reimbursement",
        "return", "partial", "adjustment", "purchase",
    },
    "KB-003": {
        "billing", "bill", "invoice", "charge", "charged",
        "payment", "subscription", "price", "plan", "dispute",
        "card", "annual",
    },
    "KB-004": {
        "shipping", "ship", "shipped", "shipment",
        "delivery", "delayed", "delay", "delivered",
        "tracking", "track", "order", "package", "parcel",
        "express", "arrived", "arrival", "dispatch",
    },
    "KB-005": {
        "technical", "crash", "crashes", "crashing", "error",
        "bug", "broken", "app", "application", "device",
        "install", "reinstall", "cache", "freeze", "freezes",
    },
    "KB-006": {
        "close", "closure", "delete", "deletion", "export",
        "privacy", "data", "permanent", "owner",
    },
}

# Normalize common variations into the same searchable term.
SYNONYMS = {
    "delayed": "delay",
    "delivering": "delivery",
    "delivered": "delivery",
    "shipment": "shipping",
    "shipped": "shipping",
    "ship": "shipping",
    "tracking": "track",
    "tracked": "track",
    "arrived": "arrival",
    "charges": "charge",
    "charged": "charge",
    "payments": "payment",
    "refunds": "refund",
    "passwords": "password",
    "crashes": "crash",
    "crashing": "crash",
    "bugs": "bug",
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())

    return {
        SYNONYMS.get(word, word)
        for word in words
        if word not in STOP_WORDS and len(word) > 1
    }


def load_articles() -> list[dict]:
    articles = []

    if not KB_DIR.exists():
        return articles

    for path in sorted(KB_DIR.glob("KB-*.md")):
        content = path.read_text(encoding="utf-8")

        match = re.search(
            r"^#\s+(KB-\d+):\s*(.+)$",
            content,
            re.MULTILINE,
        )

        if not match:
            continue

        articles.append({
            "id": match.group(1),
            "title": match.group(2).strip(),
            "content": content,
        })

    return articles


def retrieve_articles(
    subject: str,
    text: str,
    max_results: int = 2,
) -> list[dict]:
    """Rank knowledge-base articles by topic and keyword relevance."""

    query_tokens = tokenize(f"{subject} {text}")

    if not query_tokens or max_results <= 0:
        return []

    scored = []

    for article in load_articles():
        article_id = article["id"]

        # Search both the title and content.
        article_tokens = tokenize(
            f"{article['title']} {article['content']}"
        )

        topic_tokens = {
            SYNONYMS.get(word, word)
            for word in TOPIC_TERMS.get(article_id, set())
        }

        content_overlap = query_tokens & article_tokens
        topic_overlap = query_tokens & topic_tokens

        # Topic matches carry more weight than general text matches.
        score = len(content_overlap) + 2 * len(topic_overlap)

        if score > 0:
            scored.append((score, article))

    # Sort by relevance; use article ID as a stable tie-breaker.
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))

    return [
        article
        for _, article in scored[:max_results]
    ]
