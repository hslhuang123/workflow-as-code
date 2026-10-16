from __future__ import annotations

from examples.support.schemas import DraftReply, Ticket


_TICKETS = {
    "ticket_refund_123": Ticket(
        id="ticket_refund_123",
        customer_id="customer_001",
        subject="Refund for duplicate charge",
        body="I was charged twice and want a refund for the duplicate payment.",
        priority="high",
    ),
    "ticket_bug_456": Ticket(
        id="ticket_bug_456",
        customer_id="customer_002",
        subject="Dashboard crashes",
        body="The dashboard crashes with an error when I open reports.",
        priority="normal",
    ),
}

_SENT: list[dict[str, str]] = []
_ESCALATED: list[dict[str, str]] = []


def fetch_ticket(ticket_id: str) -> Ticket:
    if ticket_id not in _TICKETS:
        raise ValueError(f"unknown ticket_id {ticket_id!r}")
    return _TICKETS[ticket_id]


def send_reply(ticket: Ticket, draft: DraftReply) -> None:
    _SENT.append({"ticket_id": ticket.id, "subject": draft.subject, "body": draft.body})


def escalate_to_support(ticket: Ticket, reason: str) -> None:
    _ESCALATED.append({"ticket_id": ticket.id, "reason": reason})
