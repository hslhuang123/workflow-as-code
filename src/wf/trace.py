from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TraceError(ValueError):
    pass


def latest_trace(run_root: str | Path = "runs") -> Path:
    root = Path(run_root)
    if not root.exists():
        raise TraceError(f"no traces found under {root}")
    traces = [path for path in root.glob("*/trace.jsonl") if path.is_file()]
    if not traces:
        raise TraceError(f"no traces found under {root}")
    return max(traces, key=lambda path: path.parent.stat().st_mtime)


def format_trace(path: str | Path) -> str:
    trace_path = Path(path)
    if not trace_path.exists():
        raise TraceError(f"trace file not found: {trace_path}")
    lines: list[str] = []
    with trace_path.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise TraceError(f"malformed trace JSON in {trace_path} line {number}: {exc.msg}") from exc
            lines.append(_format_event(event))
    return "\n".join(lines)


def _format_event(event: dict[str, Any]) -> str:
    node_id = str(event.get("node_id", "<unknown>"))
    kind = str(event.get("kind", "<unknown>"))
    status = str(event.get("status", "<unknown>"))
    suffix: list[str] = []
    if "selected" in event:
        suffix.append(f"selected={event['selected']}")
    if "target" in event:
        suffix.append(f"target={event['target']}")
    if status == "failed" and event.get("error"):
        suffix.append(f"error={event['error']}")
    detail = "  " + " ".join(suffix) if suffix else ""
    return f"{node_id:<24} {kind:<8} {status}{detail}"
