from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wf.compiler import compile_file, read_ir
from wf.ir import Node, WorkflowIR


@dataclass(frozen=True)
class WorkflowListItem:
    path: Path
    status: str
    name: str | None
    nodes: int | None
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "status": self.status,
            "name": self.name,
            "nodes": self.nodes,
            "error": self.error,
        }


def list_workflows(base_dir: str | Path = "examples") -> list[WorkflowListItem]:
    base = Path(base_dir)
    paths = sorted(base.rglob("workflow.yaml")) if base.exists() else []
    items: list[WorkflowListItem] = []
    for path in paths:
        try:
            ir = compile_file(path)
            items.append(WorkflowListItem(path=path, status="valid", name=ir.name, nodes=len(ir.nodes)))
        except Exception as exc:
            items.append(WorkflowListItem(path=path, status="invalid", name=None, nodes=None, error=str(exc)))
    return items


def format_workflow_list(items: list[WorkflowListItem], *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps([item.to_json() for item in items], indent=2, sort_keys=True)
    if not items:
        return "no workflows found"
    path_width = max(len(str(item.path)) for item in items)
    rows = []
    for item in items:
        if item.status == "valid":
            rows.append(f"{str(item.path):<{path_width}}    {item.name}    {item.nodes} nodes")
        else:
            rows.append(f"{str(item.path):<{path_width}}    invalid    {_concise_error(item.error)}")
    return "\n".join(rows)


def _concise_error(error: str | None) -> str:
    lines = (error or "").splitlines()
    bullets = [index for index, line in enumerate(lines) if line.startswith("- ")]
    if not bullets:
        return lines[0] if lines else "unknown error"
    first = lines[bullets[0]][2:]
    return first if len(bullets) == 1 else f"{first} (+{len(bullets) - 1} more; run `wf validate` for details)"


def load_workflow(path: str | Path, *, is_ir: bool = False) -> WorkflowIR:
    return read_ir(path) if is_ir else compile_file(path)


def describe_workflow(ir: WorkflowIR, *, as_json: bool = False) -> str:
    data = _describe_json(ir)
    if as_json:
        return json.dumps(data, indent=2, sort_keys=True)
    lines = [
        f"Workflow: {ir.name}",
        f"Input:    {ir.input_schema}",
        f"Output:   {ir.output_schema}",
        f"Nodes:    {len(ir.nodes)}",
        "",
        "Start:",
        f"  {ir.start or (ir.nodes[0].id if ir.nodes else '<none>')}",
        "",
        "Nodes:",
    ]
    for node in ir.nodes:
        detail = _node_detail(node)
        suffix = f"  {detail}" if detail else ""
        lines.append(f"  {node.id:<22} {node.kind:<8}{suffix}")
    if ir.edges:
        lines.extend(["", "Routes:"])
        for edge in ir.edges:
            label = f".{edge.label}" if edge.label else ""
            lines.append(f"  {edge.from_node}{label} -> {edge.to_node}")
    return "\n".join(lines)


def graph_workflow(ir: WorkflowIR, *, output_format: str = "mermaid") -> str:
    if output_format == "mermaid":
        lines = ["flowchart TD"]
        for edge in ir.edges:
            if edge.label:
                lines.append(f"    {edge.from_node} -->|{edge.label}| {edge.to_node}")
            else:
                lines.append(f"    {edge.from_node} --> {edge.to_node}")
        return "\n".join(lines)
    if output_format == "dot":
        lines = ["digraph workflow {"]
        for node in ir.nodes:
            lines.append(f'  "{node.id}" [label="{node.id}\\n{node.kind}"];')
        for edge in ir.edges:
            label = f' [label="{edge.label}"]' if edge.label else ""
            lines.append(f'  "{edge.from_node}" -> "{edge.to_node}"{label};')
        lines.append("}")
        return "\n".join(lines)
    raise ValueError(f"unsupported graph format {output_format!r}; allowed: mermaid, dot")


def doctor_workflow(path: str | Path, *, input_path: str | Path | None = None, provider: str = "fake", auto_approve: bool = False, model: str | None = None, run_root: str | Path = "runs") -> tuple[bool, str]:
    from wf.providers import create_provider
    from wf.registries import Registries
    from wf.runtime import WorkflowRuntime

    lines: list[str] = []
    ok = True
    try:
        ir = compile_file(path)
        lines.append("[ok] validate")
        lines.append("[ok] compile")
        Registries.load(ir.registries)
        lines.append("[ok] registries importable")
    except Exception as exc:
        return False, f"[fail] validate/compile: {exc}"
    try:
        create_provider(provider, model=model)
        lines.append(f"[ok] provider {provider}")
    except Exception as exc:
        ok = False
        lines.append(f"[fail] provider {provider}: {exc}")
    if input_path is not None:
        input_file = Path(input_path)
        if input_file.exists():
            lines.append(f"[ok] input exists {input_file}")
            try:
                payload = json.loads(input_file.read_text(encoding="utf-8"))
                runtime = WorkflowRuntime(ir, provider=create_provider(provider, model=model), run_root=run_root)
                result = runtime.run(payload, auto_approve=auto_approve)
                lines.append(f"[ok] run {result.run_id}")
                lines.append(f"[ok] trace {result.trace_path}")
            except Exception as exc:
                ok = False
                lines.append(f"[fail] run: {exc}")
        else:
            ok = False
            lines.append(f"[fail] input missing {input_file}")
    return ok, "\n".join(lines)


def _describe_json(ir: WorkflowIR) -> dict[str, Any]:
    return {
        "name": ir.name,
        "input_schema": ir.input_schema,
        "output_schema": ir.output_schema,
        "start": ir.start,
        "nodes": [node.to_json() for node in ir.nodes],
        "edges": [edge.to_json() for edge in ir.edges],
    }


def _node_detail(node: Node) -> str:
    if node.kind == "task" and node.uses:
        return f"uses={node.uses}"
    if node.kind == "router" and node.switch:
        return f"switch={node.switch}"
    if node.kind == "agent":
        tools = ",".join(node.tools)
        return f"model={node.model} tools=[{tools}]"
    if node.kind == "human":
        return f"reviewers=[{','.join(node.reviewers)}]"
    return ""
