from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from wf.ir import Node
from wf.registries import Registries


@dataclass(frozen=True)
class AgentResult:
    output: Any
    tokens: int = 0
    tool_calls: list[dict[str, Any]] | None = None


class AgentProvider(Protocol):
    def run_agent(
        self,
        *,
        node: Node,
        inputs: dict[str, Any],
        registries: Registries,
    ) -> AgentResult:
        ...
