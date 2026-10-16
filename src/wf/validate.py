from __future__ import annotations

from collections import defaultdict, deque

from wf import expressions
from wf.ir import Node, WorkflowIR
from wf.registries import Registries, RegistryError


class WorkflowValidationError(ValueError):
    pass


def validate_ir(ir: WorkflowIR, *, check_registries: bool = True) -> None:
    errors: list[str] = []
    errors.extend(_validate_top_level(ir))
    node_by_id = {node.id: node for node in ir.nodes}
    errors.extend(_validate_node_ids(ir.nodes))
    errors.extend(_validate_nodes(ir.nodes))
    errors.extend(_validate_edges(ir, node_by_id))
    errors.extend(_validate_references(ir, node_by_id))
    errors.extend(_validate_reachability(ir, node_by_id))
    if check_registries:
        errors.extend(_validate_registries(ir))
    if errors:
        raise WorkflowValidationError("workflow validation failed:\n- " + "\n- ".join(errors))


def _validate_top_level(ir: WorkflowIR) -> list[str]:
    errors: list[str] = []
    for key in ["name", "version", "input_schema", "output_schema"]:
        if not getattr(ir, key):
            errors.append(f"missing {key}")
    if not ir.nodes:
        errors.append("workflow must contain at least one node")
    if ir.start and ir.start not in {node.id for node in ir.nodes}:
        errors.append(f"start node {ir.start!r} does not exist")
    return errors


def _validate_node_ids(nodes: list[Node]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        if not node.id:
            errors.append("node id is required")
        if node.id in seen:
            errors.append(f"duplicate node id {node.id!r}")
        seen.add(node.id)
    return errors


def _validate_nodes(nodes: list[Node]) -> list[str]:
    errors: list[str] = []
    allowed = {"task", "agent", "router", "human", "output"}
    for node in nodes:
        prefix = f"node {node.id!r}"
        if node.kind not in allowed:
            errors.append(f"{prefix}: unknown kind {node.kind!r}")
            continue
        try:
            expressions.validate_expression_syntax(node.input, context=f"{prefix}.input")
            expressions.validate_expression_syntax(node.value, context=f"{prefix}.value")
            if node.switch:
                expressions.validate_expression_syntax(node.switch, context=f"{prefix}.switch")
        except Exception as exc:
            errors.append(str(exc))
        if node.kind == "task":
            if not node.uses:
                errors.append(f"{prefix}: task requires uses")
            if node.model or node.instructions or node.tools:
                errors.append(f"{prefix}: task cannot define model, instructions, or tools")
        elif node.kind == "agent":
            for field in ["model", "instructions", "output_schema"]:
                if not getattr(node, field):
                    errors.append(f"{prefix}: agent requires {field}")
            if not isinstance(node.tools, list):
                errors.append(f"{prefix}: tools must be a list")
        elif node.kind == "router":
            if not node.switch:
                errors.append(f"{prefix}: router requires switch")
            if not node.cases:
                errors.append(f"{prefix}: router requires cases")
        elif node.kind == "human":
            if not node.reviewers:
                errors.append(f"{prefix}: human requires reviewers")
        elif node.kind == "output":
            if node.value is None:
                errors.append(f"{prefix}: output requires value")
    return errors


def _validate_edges(ir: WorkflowIR, node_by_id: dict[str, Node]) -> list[str]:
    errors: list[str] = []
    for edge in ir.edges:
        if edge.from_node not in node_by_id:
            errors.append(f"edge from unknown node {edge.from_node!r}")
        if edge.to_node not in node_by_id:
            errors.append(f"edge to unknown node {edge.to_node!r}")
    return errors


def _validate_references(ir: WorkflowIR, node_by_id: dict[str, Node]) -> list[str]:
    errors: list[str] = []
    ids = set(node_by_id)
    for node in ir.nodes:
        if node.next and node.next not in ids:
            errors.append(f"node {node.id!r}: next node {node.next!r} does not exist")
        for label, target in node.cases.items():
            if target not in ids:
                errors.append(f"node {node.id!r}: case {label!r} targets missing node {target!r}")
        values = [node.input, node.value]
        if node.switch:
            values.append(node.switch)
        for value in values:
            for expr in expressions.find_expressions(value):
                parts = expr.split(".")
                if len(parts) >= 2 and parts[0] == "nodes" and parts[1] not in ids:
                    errors.append(f"node {node.id!r}: expression references missing node {parts[1]!r}")
    return errors


def _validate_reachability(ir: WorkflowIR, node_by_id: dict[str, Node]) -> list[str]:
    if not ir.nodes:
        return []
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node.id: 0 for node in ir.nodes}
    for edge in ir.edges:
        if edge.from_node in node_by_id and edge.to_node in node_by_id:
            adjacency[edge.from_node].append(edge.to_node)
            indegree[edge.to_node] += 1
    starts = [node_id for node_id, degree in indegree.items() if degree == 0]
    if ir.start:
        starts = [ir.start]
    errors: list[str] = []
    if len(starts) != 1:
        errors.append(f"workflow must have exactly one start node, found {len(starts)}")
        return errors
    reachable: set[str] = set()
    stack = [starts[0]]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(adjacency[current])
    unreachable = sorted(set(node_by_id) - reachable)
    if unreachable:
        errors.append(f"unreachable nodes: {', '.join(unreachable)}")
    cycle_nodes = _cycle_nodes(adjacency, set(node_by_id))
    if cycle_nodes:
        errors.append(f"cycles are not supported in MVP: {', '.join(sorted(cycle_nodes))}")
    return errors


def _cycle_nodes(adjacency: dict[str, list[str]], ids: set[str]) -> set[str]:
    indegree = {node_id: 0 for node_id in ids}
    for source in ids:
        for target in adjacency[source]:
            indegree[target] += 1
    queue = deque([node_id for node_id, degree in indegree.items() if degree == 0])
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited == len(ids):
        return set()
    return {node_id for node_id, degree in indegree.items() if degree > 0}


def _validate_registries(ir: WorkflowIR) -> list[str]:
    errors: list[str] = []
    try:
        registries = Registries.load(ir.registries)
    except RegistryError as exc:
        return [str(exc)]
    if not registries.has_schema(ir.input_schema):
        errors.append(f"unknown input schema {ir.input_schema!r}")
    if not registries.has_schema(ir.output_schema):
        errors.append(f"unknown output schema {ir.output_schema!r}")
    for node in ir.nodes:
        if node.kind == "task" and node.uses and not registries.has_task(node.uses):
            errors.append(f"node {node.id!r}: unknown task {node.uses!r}")
        if node.kind == "agent":
            if node.output_schema and not registries.has_schema(node.output_schema):
                errors.append(f"node {node.id!r}: unknown output schema {node.output_schema!r}")
            for tool in node.tools:
                if not registries.has_tool(tool):
                    errors.append(f"node {node.id!r}: unknown tool {tool!r}")
    return errors
