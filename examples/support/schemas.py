from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TicketInput:
    ticket_id: str


@dataclass(frozen=True)
class Ticket:
    id: str
    customer_id: str
    subject: str
    body: str
    priority: Literal["low", "normal", "high"]


@dataclass(frozen=True)
class Classification:
    category: Literal["refund", "bug", "billing", "how_to", "other"]
    confidence: float
    rationale: str


@dataclass(frozen=True)
class DraftReply:
    subject: str
    body: str
    needs_human_review: bool


@dataclass(frozen=True)
class TriageResult:
    ticket_id: str
    category: str
    reply_sent: bool
    escalated: bool
