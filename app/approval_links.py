"""Signed, expiring Approve/Reject links for the approval email.

A token carries the ticket ID, the decision and an expiry time, signed with
HMAC-SHA256 so it cannot be changed without the secret. Opening a link only
shows a confirmation page; the decision is recorded when the manager presses
Confirm. Uses the standard library only.
"""

import base64
import binascii
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime

DECISION_CODES = {"Accept": "A", "Reject": "R"}
_DECISIONS_BY_CODE = {code: decision for decision, code in DECISION_CODES.items()}

_TICKET_ID_RE = re.compile(r"^TCK-\d{1,10}$")

# base64url payload "." base64url signature. Checked up front because the
# decoder would otherwise silently skip characters outside the alphabet.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")

# Real tokens are under 100 characters; anything much longer is not ours.
MAX_TOKEN_LENGTH = 300


class InvalidLink(Exception):
    """The token is malformed, changed, or signed with another secret."""


class ExpiredLink(Exception):
    """The token is genuine but past its expiry. Holds what it was for."""

    def __init__(self, claims: "LinkClaims"):
        super().__init__(claims.ticket_id)
        self.claims = claims


@dataclass(frozen=True)
class LinkClaims:
    ticket_id: str
    decision: str
    expires_at: datetime


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise InvalidLink() from None


def _signature(payload: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()


def make_token(ticket_id: str, decision: str, expires_at: datetime, secret: str) -> str:
    """URL-safe token: base64url(payload) "." base64url(signature), no padding."""
    if decision not in DECISION_CODES:
        raise ValueError("decision must be Accept or Reject")
    payload = f"{ticket_id}|{DECISION_CODES[decision]}|{int(expires_at.timestamp())}"
    data = payload.encode("utf-8")
    return f"{_encode(data)}.{_encode(_signature(data, secret))}"


def read_token(token: str, secret: str, now: datetime) -> LinkClaims:
    """The token's claims. Raises InvalidLink or ExpiredLink."""
    if not token or len(token) > MAX_TOKEN_LENGTH or not _TOKEN_RE.match(token):
        raise InvalidLink()
    encoded_payload, encoded_signature = token.split(".")
    payload = _decode(encoded_payload)
    if not hmac.compare_digest(_decode(encoded_signature), _signature(payload, secret)):
        raise InvalidLink()

    try:
        ticket_id, code, expires = payload.decode("utf-8").split("|")
        expires_at = datetime.fromtimestamp(int(expires))
    except (UnicodeError, ValueError, OverflowError, OSError):
        raise InvalidLink() from None
    if not _TICKET_ID_RE.match(ticket_id) or code not in _DECISIONS_BY_CODE:
        raise InvalidLink()

    claims = LinkClaims(ticket_id, _DECISIONS_BY_CODE[code], expires_at)
    if now > expires_at:
        raise ExpiredLink(claims)
    return claims


def link_for(public_base_url: str, token: str) -> str:
    # The token only uses URL-safe characters, so it needs no quoting.
    return f"{public_base_url}/approvals/respond?token={token}"
