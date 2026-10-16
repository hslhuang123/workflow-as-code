"""LangGraph adapter boundary.

The MVP executes the generic IR directly so validate/compile/run work without a
LangGraph dependency. A future adapter should consume the same IR models from
``wf.ir`` and construct an equivalent LangGraph graph here.
"""

from __future__ import annotations

from wf.ir import WorkflowIR


def describe_adapter(ir: WorkflowIR) -> dict[str, object]:
    """Return deterministic adapter metadata for diagnostics and tests."""
    return {
        "backend": "langgraph",
        "workflow": ir.name,
        "nodes": len(ir.nodes),
        "status": "adapter-boundary-defined",
    }
