from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NodeKind = Literal["task", "agent", "router", "human", "output"]


@dataclass(frozen=True)
class Edge:
    from_node: str
    to_node: str
    label: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = {"from": self.from_node, "to": self.to_node}
        if self.label is not None:
            data["label"] = self.label
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Edge":
        return cls(from_node=str(data["from"]), to_node=str(data["to"]), label=data.get("label"))


@dataclass
class Node:
    id: str
    kind: NodeKind
    uses: str | None = None
    model: str | None = None
    instructions: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    output_schema: str | None = None
    tools: list[str] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)
    retry: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int | None = None
    switch: str | None = None
    cases: dict[str, str] = field(default_factory=dict)
    reviewers: list[str] = field(default_factory=list)
    next: str | None = None
    value: Any = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Node":
        known = {
            "id",
            "kind",
            "uses",
            "model",
            "instructions",
            "input",
            "output_schema",
            "tools",
            "policy",
            "retry",
            "timeout_seconds",
            "switch",
            "cases",
            "reviewers",
            "next",
            "value",
        }
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"node {data.get('id', '<unknown>')}: unknown fields: {', '.join(unknown)}")
        return cls(
            id=str(data["id"]),
            kind=data["kind"],
            uses=data.get("uses"),
            model=data.get("model"),
            instructions=data.get("instructions"),
            input=dict(data.get("input") or {}),
            output_schema=data.get("output_schema"),
            tools=list(data.get("tools") or []),
            policy=dict(data.get("policy") or {}),
            retry=dict(data.get("retry") or {}),
            timeout_seconds=data.get("timeout_seconds"),
            switch=data.get("switch"),
            cases=dict(data.get("cases") or {}),
            reviewers=list(data.get("reviewers") or []),
            next=data.get("next"),
            value=data.get("value"),
        )

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "kind": self.kind}
        optional = [
            ("uses", self.uses),
            ("model", self.model),
            ("instructions", self.instructions),
            ("input", self.input),
            ("output_schema", self.output_schema),
            ("tools", self.tools),
            ("policy", self.policy),
            ("retry", self.retry),
            ("timeout_seconds", self.timeout_seconds),
            ("switch", self.switch),
            ("cases", self.cases),
            ("reviewers", self.reviewers),
            ("next", self.next),
            ("value", self.value),
        ]
        for key, value in optional:
            if value not in (None, {}, []):
                data[key] = value
        return data


@dataclass
class WorkflowIR:
    ir_version: str
    name: str
    version: str
    input_schema: str
    output_schema: str
    registries: dict[str, str]
    nodes: list[Node]
    edges: list[Edge]
    start: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "WorkflowIR":
        return cls(
            ir_version=str(data.get("ir_version", "0.1.0")),
            name=str(data["name"]),
            version=str(data["version"]),
            input_schema=str(data["input_schema"]),
            output_schema=str(data["output_schema"]),
            registries=dict(data.get("registries") or {}),
            nodes=[Node.from_json(item) for item in data.get("nodes", [])],
            edges=[Edge.from_json(item) for item in data.get("edges", [])],
            start=data.get("start"),
        )

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ir_version": self.ir_version,
            "name": self.name,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "registries": dict(sorted(self.registries.items())),
            "nodes": [node.to_json() for node in self.nodes],
            "edges": [edge.to_json() for edge in self.edges],
        }
        if self.start:
            data["start"] = self.start
        return data
