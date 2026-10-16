from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from wf.ir import Node
from wf.providers.base import AgentResult
from wf.registries import Registries, to_plain


class FakeAgentProvider:
    """Deterministic MVP provider for local smoke runs and tests.

    It enforces the same provider boundary as a real LLM adapter: inputs in,
    registered tools available, structured output out. It intentionally avoids
    network access so the MVP can be verified without credentials.
    """

    def run_agent(self, *, node: Node, inputs: dict[str, Any], registries: Registries) -> AgentResult:
        if node.id == "classify_ticket":
            ticket = _plain(inputs["ticket"])
            text = f"{ticket.get('subject', '')} {ticket.get('body', '')}".lower()
            if any(term in text for term in ["refund", "cancel", "money back", "charged"]):
                category = "refund"
            elif any(term in text for term in ["bug", "broken", "error", "crash"]):
                category = "bug"
            elif any(term in text for term in ["invoice", "billing", "receipt", "payment"]):
                category = "billing"
            elif any(term in text for term in ["how", "setup", "configure", "use"]):
                category = "how_to"
            else:
                category = "other"
            return AgentResult(
                output={
                    "category": category,
                    "confidence": 0.9,
                    "rationale": f"Fake provider matched ticket text to {category}.",
                },
                tokens=128,
                tool_calls=[],
            )
        if node.output_schema == "DraftReply":
            ticket = _plain(inputs.get("ticket", {}))
            subject = ticket.get("subject", "Support request")
            return AgentResult(
                output={
                    "subject": f"Re: {subject}",
                    "body": "Thanks for contacting support. We reviewed your request and will help with the next step.",
                    "needs_human_review": node.id == "draft_refund_reply",
                },
                tokens=192,
                tool_calls=[{"tool": tool, "status": "available_not_called"} for tool in node.tools],
            )
        schema = registries.schema(node.output_schema or "")
        raise ValueError(f"fake provider has no fixture for node {node.id!r} / schema {schema.__name__}")


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return to_plain(value)
