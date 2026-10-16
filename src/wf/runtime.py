from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wf import expressions
from wf.ir import Node, WorkflowIR
from wf.providers.base import AgentProvider
from wf.providers.fake import FakeAgentProvider
from wf.registries import Registries, to_plain, validate_call_inputs, validate_return, validate_value
from wf.validate import validate_ir


class RuntimeError(ValueError):
    pass


@dataclass
class RunResult:
    run_id: str
    output: Any
    trace_path: Path


class WorkflowRuntime:
    def __init__(self, ir: WorkflowIR, *, provider: AgentProvider | None = None, run_root: str | Path = "runs"):
        validate_ir(ir)
        self.ir = ir
        self.provider = provider or FakeAgentProvider()
        self.registries = Registries.load(ir.registries)
        self.node_by_id = {node.id: node for node in ir.nodes}
        self.edges = ir.edges
        self.run_root = Path(run_root)

    def run(self, input_payload: dict[str, Any], *, auto_approve: bool = False) -> RunResult:
        run_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        run_dir = self.run_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        trace_path = run_dir / "trace.jsonl"
        input_schema = self.registries.schema(self.ir.input_schema)
        checked_input = validate_value(input_schema, input_payload, context="input")
        state: dict[str, Any] = {"input": to_plain(checked_input), "nodes": {}}
        current = self.ir.start or self.ir.nodes[0].id
        output: Any = None
        visited = 0
        while current:
            visited += 1
            if visited > len(self.ir.nodes) + 1:
                raise RuntimeError("runtime detected a cycle or runaway execution")
            node = self.node_by_id[current]
            start = time.time()
            event: dict[str, Any] = {"run_id": run_id, "node_id": node.id, "kind": node.kind, "status": "started", "started_at": start}
            try:
                node_output, next_node, extra = self._execute_node(node, state, auto_approve=auto_approve)
                state["nodes"][node.id] = to_plain(node_output)
                event.update(extra)
                event["status"] = "succeeded"
                event["duration_ms"] = int((time.time() - start) * 1000)
                event["output_summary"] = _summary(node_output)
                _append_trace(trace_path, event)
                if node.kind == "output":
                    output_schema = self.registries.schema(self.ir.output_schema)
                    output = validate_value(output_schema, to_plain(node_output), context="output")
                    break
                current = next_node
            except Exception as exc:
                event["status"] = "failed"
                event["duration_ms"] = int((time.time() - start) * 1000)
                event["error"] = str(exc)
                _append_trace(trace_path, event)
                raise
        if output is None:
            raise RuntimeError("workflow finished without output node")
        return RunResult(run_id=run_id, output=to_plain(output), trace_path=trace_path)

    def _execute_node(self, node: Node, state: dict[str, Any], *, auto_approve: bool) -> tuple[Any, str | None, dict[str, Any]]:
        if node.kind == "task":
            return self._execute_task(node, state)
        if node.kind == "agent":
            return self._execute_agent(node, state)
        if node.kind == "router":
            selected = expressions.resolve(node.switch, state)
            target = node.cases.get(str(selected), node.cases.get("default"))
            if not target:
                raise RuntimeError(f"router {node.id!r} has no case for {selected!r} and no default")
            return {"selected": selected, "target": target}, target, {"selected": selected, "target": target}
        if node.kind == "human":
            payload = expressions.resolve(node.input, state)
            if not auto_approve:
                print(f"Human approval required for {node.id}")
                print(json.dumps(to_plain(payload), indent=2, sort_keys=True))
                print("Auto-approving is disabled. Re-run with --auto-approve for non-interactive MVP runs.")
                raise RuntimeError(f"human node {node.id!r} requires approval")
            if isinstance(payload, dict) and "draft" in payload:
                output = payload["draft"]
            else:
                output = payload
            return output, self._next_after(node), {"approved": True, "reviewers": node.reviewers}
        if node.kind == "output":
            return expressions.resolve(node.value, state), None, {}
        raise RuntimeError(f"unsupported node kind {node.kind!r}")

    def _execute_task(self, node: Node, state: dict[str, Any]) -> tuple[Any, str | None, dict[str, Any]]:
        if not node.uses:
            raise RuntimeError(f"task node {node.id!r} missing uses")
        func = self.registries.task(node.uses)
        raw_inputs = expressions.resolve(node.input, state)
        inputs = validate_call_inputs(func, raw_inputs, context=f"node {node.id}")
        result = func(**inputs)
        result = validate_return(func, result, context=f"node {node.id}.output")
        return result, self._next_after(node), {}

    def _execute_agent(self, node: Node, state: dict[str, Any]) -> tuple[Any, str | None, dict[str, Any]]:
        for tool in node.tools:
            self.registries.tool(tool)
        inputs = expressions.resolve(node.input, state)
        result = self.provider.run_agent(node=node, inputs=inputs, registries=self.registries)
        schema = self.registries.schema(node.output_schema or "")
        checked = validate_value(schema, result.output, context=f"node {node.id}.output")
        return checked, self._next_after(node), {"tokens": result.tokens, "tool_calls": result.tool_calls or []}

    def _next_after(self, node: Node) -> str | None:
        if node.next:
            return node.next
        outgoing = [edge for edge in self.edges if edge.from_node == node.id]
        if not outgoing:
            return None
        if len(outgoing) > 1:
            raise RuntimeError(f"node {node.id!r} has ambiguous outgoing edges")
        return outgoing[0].to_node


def _append_trace(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _summary(value: Any) -> Any:
    plain = to_plain(value)
    if isinstance(plain, dict):
        return {key: type(val).__name__ for key, val in plain.items()}
    if isinstance(plain, list):
        return f"list[{len(plain)}]"
    return plain
