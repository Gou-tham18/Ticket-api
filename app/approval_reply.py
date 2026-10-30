"""Read the decisions a manager wrote in a reply to the approval email.

The manager writes APPROVE or REJECT after "Decision:" for each ticket and
replies. Email clients usually quote the original message below the reply,
so the same ticket ID can appear more than once: once with the manager's
answer and once, blank, in the quoted original.
"""

import re
from typing import Dict, List

TICKET_ID_PATTERN = re.compile(r"TCK-\d+")

ACCEPT_WORDS = ("approve", "approved", "accept", "accepted", "ok", "yes")
REJECT_WORDS = ("reject", "rejected", "decline", "declined", "no")

_ACCEPT_RE = re.compile(r"\b(?:" + "|".join(ACCEPT_WORDS) + r")\b", re.IGNORECASE)
_REJECT_RE = re.compile(r"\b(?:" + "|".join(REJECT_WORDS) + r")\b", re.IGNORECASE)

# The email's instruction line names both outcomes. If it is quoted below
# the manager's answers it must not make the last ticket look conflicting.
_INSTRUCTION_RE = re.compile(r"approve\s+or\s+reject", re.IGNORECASE)

# Leading quote markers such as "> " or ">> ".
_QUOTE_PREFIX_RE = re.compile(r"^[>\s]+")

ACCEPT = "accept"
REJECT = "reject"
BLANK = "blank"
UNCLEAR = "unclear"


class NoTicketsInReply(ValueError):
    """The pasted text does not mention any ticket ID."""


def _clean_text(reply_text: str) -> str:
    lines = []
    for line in reply_text.splitlines():
        line = _QUOTE_PREFIX_RE.sub("", line)
        if _INSTRUCTION_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def _block_decision(block: str) -> str:
    accepts = bool(_ACCEPT_RE.search(block))
    rejects = bool(_REJECT_RE.search(block))
    if accepts and rejects:
        return UNCLEAR
    if accepts:
        return ACCEPT
    if rejects:
        return REJECT
    return BLANK


def parse_reply(reply_text: str) -> Dict[str, str]:
    """Map each ticket ID to accept, reject, blank, or unclear.

    Tickets are returned in the order they first appear. Text before the
    first ticket ID is ignored. Each occurrence's decision comes from the
    text between it and the next ticket ID. Blank occurrences are ignored
    when the same ticket also has a written answer; answers that disagree
    make the ticket unclear.
    """
    text = _clean_text(reply_text)
    matches = list(TICKET_ID_PATTERN.finditer(text))
    if not matches:
        raise NoTicketsInReply("The reply does not contain any ticket IDs (like TCK-5007).")

    occurrences: Dict[str, List[str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        occurrences.setdefault(match.group(), []).append(_block_decision(block))

    decisions = {}
    for ticket_id, found in occurrences.items():
        written = {decision for decision in found if decision != BLANK}
        if not written:
            decisions[ticket_id] = BLANK
        elif len(written) > 1 or UNCLEAR in written:
            decisions[ticket_id] = UNCLEAR
        else:
            decisions[ticket_id] = written.pop()
    return decisions
