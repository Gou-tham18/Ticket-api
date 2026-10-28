from app.retrieval import retrieve_articles


def test_password_ticket_retrieves_password_article():
    articles = retrieve_articles(
        "Cannot reset password",
        "The reset email never arrived and I cannot sign in.",
    )
    assert articles
    assert articles[0]["id"] == "KB-001"


def test_refund_ticket_retrieves_refund_article():
    articles = retrieve_articles(
        "Where is my refund?",
        "I requested my money back for a recent purchase.",
    )
    assert articles
    assert articles[0]["id"] == "KB-002"


def test_unrelated_ticket_has_no_matching_articles():
    articles = retrieve_articles(
        "Question about the weather",
        "Will it rain in Chennai tomorrow?",
    )
    assert articles == []


def test_retrieval_returns_at_most_two_articles():
    articles = retrieve_articles(
        "Billing refund",
        "I was charged for a subscription and want a refund.",
    )
    assert len(articles) <= 2