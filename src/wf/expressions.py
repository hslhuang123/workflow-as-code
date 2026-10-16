from __future__ import annotations

import re
from dataclasses import is_dataclass
from typing import Any

_EXPR = re.compile(r"^\$\{([^}]+)\}$")
_EXPR_ANY = re.compile(r"\$\{([^}]+)\}")
_REF = re.compile(r"^(input|nodes)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


class ExpressionError(ValueError):
    pass


def find_expressions(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.extend(match.group(1).strip() for match in _EXPR_ANY.finditer(value))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(find_expressions(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_expressions(item))
    return found


def validate_expression_syntax(value: Any, *, context: str) -> None:
    for expr in find_expressions(value):
        if not _REF.match(expr):
            raise ExpressionError(f"{context}: unsupported expression ${{{expr}}}; use input.x or nodes.<id>.output.y")


def resolve(value: Any, state: dict[str, Any]) -> Any:
    if isinstance(value, str):
        exact = _EXPR.match(value)
        if exact:
            return _resolve_ref(exact.group(1).strip(), state)
        return _EXPR_ANY.sub(lambda match: str(_resolve_ref(match.group(1).strip(), state)), value)
    if isinstance(value, dict):
        return {key: resolve(val, state) for key, val in value.items()}
    if isinstance(value, list):
        return [resolve(item, state) for item in value]
    return value


def _resolve_ref(ref: str, state: dict[str, Any]) -> Any:
    parts = ref.split(".")
    if not parts:
        raise ExpressionError("empty expression")
    if parts[0] == "input":
        current: Any = state.get("input")
        parts = parts[1:]
    elif parts[0] == "nodes":
        if len(parts) < 3 or parts[2] != "output":
            raise ExpressionError(f"unsupported node reference ${{{ref}}}; expected nodes.<id>.output")
        node_id = parts[1]
        outputs = state.get("nodes", {})
        if node_id not in outputs:
            raise ExpressionError(f"node {node_id!r} has no output yet")
        current = outputs[node_id]
        parts = parts[3:]
    else:
        raise ExpressionError(f"unsupported reference root {parts[0]!r}")
    for part in parts:
        current = _get(current, part, ref)
    return current


def _get(value: Any, key: str, ref: str) -> Any:
    if isinstance(value, dict):
        if key not in value:
            raise ExpressionError(f"reference ${{{ref}}} missing key {key!r}")
        return value[key]
    if is_dataclass(value):
        if not hasattr(value, key):
            raise ExpressionError(f"reference ${{{ref}}} missing field {key!r}")
        return getattr(value, key)
    if hasattr(value, key):
        return getattr(value, key)
    raise ExpressionError(f"reference ${{{ref}}} cannot read {key!r} from {type(value).__name__}")
