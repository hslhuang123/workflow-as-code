from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wf.ir import Edge, Node, WorkflowIR
from wf.validate import validate_ir
from wf.yaml_loader import load_yaml_file


class CompileError(ValueError):
    pass


def compile_file(path: str | Path) -> WorkflowIR:
    data = load_yaml_file(path)
    ir = compile_mapping(data)
    validate_ir(ir)
    return ir


def compile_mapping(data: dict[str, Any]) -> WorkflowIR:
    required = ["name", "version", "input_schema", "output_schema", "registries", "nodes"]
    missing = [key for key in required if key not in data]
    if missing:
        raise CompileError(f"workflow missing required fields: {', '.join(missing)}")
    nodes_raw = data["nodes"]
    if not isinstance(nodes_raw, list):
        raise CompileError("workflow nodes must be a list")
    nodes = [Node.from_json(item) for item in nodes_raw]
    edges = _derive_edges(nodes)
    return WorkflowIR(
        ir_version=str(data.get("ir_version", "0.1.0")),
        name=str(data["name"]),
        version=str(data["version"]),
        input_schema=str(data["input_schema"]),
        output_schema=str(data["output_schema"]),
        registries=dict(data["registries"]),
        nodes=nodes,
        edges=edges,
        start=data.get("start") or (nodes[0].id if nodes else None),
    )


def write_ir(ir: WorkflowIR, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(ir.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_ir(path: str | Path) -> WorkflowIR:
    return WorkflowIR.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _derive_edges(nodes: list[Node]) -> list[Edge]:
    edges: list[Edge] = []
    for index, node in enumerate(nodes):
        if node.kind == "output":
            continue
        if node.kind == "router":
            for label, target in sorted(node.cases.items()):
                edges.append(Edge(from_node=node.id, to_node=target, label=label))
            continue
        if node.next:
            edges.append(Edge(from_node=node.id, to_node=node.next))
        elif index + 1 < len(nodes):
            next_node = nodes[index + 1]
            edges.append(Edge(from_node=node.id, to_node=next_node.id))
    return edges
