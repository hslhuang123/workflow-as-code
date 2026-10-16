from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path


class ScaffoldError(ValueError):
    pass


TEMPLATES = ("basic", "router", "agent", "human")


@dataclass(frozen=True)
class ScaffoldResult:
    name: str
    directory: Path
    workflow_path: Path
    input_path: Path
    test_path: Path | None = None


def init_workflow(
    raw_name: str,
    *,
    template: str = "basic",
    base_dir: str | Path = "examples",
    force: bool = False,
    with_test: bool = False,
    tests_dir: str | Path = "tests",
) -> ScaffoldResult:
    if template not in TEMPLATES:
        allowed = ", ".join(TEMPLATES)
        raise ScaffoldError(f"unknown template {template!r}; allowed templates: {allowed}")
    name = normalize_name(raw_name)
    base = Path(base_dir)
    _validate_package_path(base)
    target = base / name
    if target.exists():
        if not force:
            raise ScaffoldError(f"workflow folder already exists: {target}; use --force to replace it")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=False)
    _ensure_package_markers(base)
    (target / "__init__.py").write_text("", encoding="utf-8")

    package = ".".join([*base.parts, name])
    files = _render_template(template, name=name, package=package)
    for filename, content in files.items():
        (target / filename).write_text(content, encoding="utf-8")

    test_path = None
    if with_test:
        tests = Path(tests_dir)
        tests.mkdir(parents=True, exist_ok=True)
        test_path = tests / f"test_{name}.py"
        test_path.write_text(_render_test(name=name, workflow_dir=target), encoding="utf-8")

    return ScaffoldResult(
        name=name,
        directory=target,
        workflow_path=target / "workflow.yaml",
        input_path=target / "input.json",
        test_path=test_path,
    )


def normalize_name(raw_name: str) -> str:
    if any(separator in raw_name for separator in ("/", "\\")) or ".." in raw_name:
        raise ScaffoldError(f"unsafe workflow name {raw_name!r}: path separators and '..' are not allowed")
    normalized = raw_name.strip().lower().replace("-", " ")
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise ScaffoldError(f"workflow name {raw_name!r} is empty after normalization")
    return normalized


def _validate_package_path(path: Path) -> None:
    for part in path.parts:
        if part in {".", ""}:
            continue
        if part == "..":
            raise ScaffoldError(f"unsafe destination {path}: '..' is not allowed")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", part):
            raise ScaffoldError(f"destination {path} is not importable as a Python package")


def _ensure_package_markers(base: Path) -> None:
    current = Path()
    for part in base.parts:
        current = current / part
        current.mkdir(exist_ok=True)
        marker = current / "__init__.py"
        if not marker.exists():
            marker.write_text("", encoding="utf-8")


def _render_template(template: str, *, name: str, package: str) -> dict[str, str]:
    if template == "basic":
        return _basic_template(name=name, package=package)
    if template == "router":
        return _router_template(name=name, package=package)
    if template == "agent":
        return _agent_template(name=name, package=package)
    if template == "human":
        return _human_template(name=name, package=package)
    raise AssertionError(template)


def _common_workflow_header(name: str, package: str, input_schema: str, output_schema: str) -> str:
    return f"""name: {name}
version: 0.1.0

input_schema: {input_schema}
output_schema: {output_schema}

registries:
  tasks: {package}.tasks
  tools: {package}.tools
  schemas: {package}.schemas
"""


def _basic_template(*, name: str, package: str) -> dict[str, str]:
    return {
        "schemas.py": """from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BasicInput:
    name: str


@dataclass(frozen=True)
class Greeting:
    message: str


@dataclass(frozen=True)
class BasicResult:
    message: str
""",
        "tasks.py": f"""from __future__ import annotations

from {package}.schemas import Greeting


def create_greeting(name: str) -> Greeting:
    return Greeting(message=f"Welcome aboard, {{name}} — your workflow is running!")
""",
        "tools.py": '"""No agent tools are needed for this workflow."""\n',
        "input.json": '{\n  "name": "Nova"\n}\n',
        "workflow.yaml": _common_workflow_header(name, package, "BasicInput", "BasicResult") + """
nodes:
  - id: create_greeting
    kind: task
    uses: create_greeting
    input:
      name: "${input.name}"

  - id: finish
    kind: output
    value:
      message: "${nodes.create_greeting.output.message}"
""",
    }


def _router_template(*, name: str, package: str) -> dict[str, str]:
    return {
        "schemas.py": """from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RouterInput:
    status: Literal["approved", "rejected"]


@dataclass(frozen=True)
class StatusCheck:
    status: Literal["approved", "rejected"]


@dataclass(frozen=True)
class RouterResult:
    status: str
    message: str
""",
        "tasks.py": f"""from __future__ import annotations

from {package}.schemas import StatusCheck


def check_status(status: str) -> StatusCheck:
    if status not in {{"approved", "rejected"}}:
        raise ValueError(f"unsupported status {{status!r}}")
    return StatusCheck(status=status)
""",
        "tools.py": '"""No agent tools are needed for this workflow."""\n',
        "input.json": '{\n  "status": "approved"\n}\n',
        "workflow.yaml": _common_workflow_header(name, package, "RouterInput", "RouterResult") + """
nodes:
  - id: check_status
    kind: task
    uses: check_status
    input:
      status: "${input.status}"

  - id: route_status
    kind: router
    switch: "${nodes.check_status.output.status}"
    cases:
      approved: finish_approved
      rejected: finish_rejected

  - id: finish_approved
    kind: output
    value:
      status: approved
      message: "Approved path selected"

  - id: finish_rejected
    kind: output
    value:
      status: rejected
      message: "Rejected path selected"
""",
    }


def _agent_template(*, name: str, package: str) -> dict[str, str]:
    return {
        "schemas.py": """from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AgentInput:
    message: str


@dataclass(frozen=True)
class Ticket:
    id: str
    subject: str
    body: str


@dataclass(frozen=True)
class Classification:
    category: Literal["refund", "bug", "billing", "how_to", "other"]
    confidence: float
    rationale: str


@dataclass(frozen=True)
class AgentResult:
    category: str
    rationale: str
""",
        "tasks.py": f"""from __future__ import annotations

from {package}.schemas import Ticket


def make_ticket(message: str) -> Ticket:
    return Ticket(id="ticket_001", subject="Generated ticket", body=message)
""",
        "tools.py": """from __future__ import annotations


def search_knowledge_base(query: str) -> list[str]:
    return [f"Knowledge-base result for: {query}"]
""",
        "input.json": '{\n  "message": "The dashboard is broken and shows an error."\n}\n',
        "workflow.yaml": _common_workflow_header(name, package, "AgentInput", "AgentResult") + """
nodes:
  - id: make_ticket
    kind: task
    uses: make_ticket
    input:
      message: "${input.message}"

  - id: classify_ticket
    kind: agent
    model: fake-local
    instructions: |
      Classify the ticket into refund, bug, billing, how_to, or other.
      Return a Classification object.
    input:
      ticket: "${nodes.make_ticket.output}"
    output_schema: Classification
    tools:
      - search_knowledge_base
    policy:
      max_steps: 2
      max_tokens: 500

  - id: finish
    kind: output
    value:
      category: "${nodes.classify_ticket.output.category}"
      rationale: "${nodes.classify_ticket.output.rationale}"
""",
    }


def _human_template(*, name: str, package: str) -> dict[str, str]:
    return {
        "schemas.py": """from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HumanInput:
    name: str


@dataclass(frozen=True)
class Draft:
    message: str


@dataclass(frozen=True)
class HumanResult:
    message: str
    approved: bool
""",
        "tasks.py": f"""from __future__ import annotations

from {package}.schemas import Draft


def create_draft(name: str) -> Draft:
    return Draft(message=f"Hello, {{name}}!")
""",
        "tools.py": '"""No agent tools are needed for this workflow."""\n',
        "input.json": '{\n  "name": "Nova"\n}\n',
        "workflow.yaml": _common_workflow_header(name, package, "HumanInput", "HumanResult") + """
nodes:
  - id: create_draft
    kind: task
    uses: create_draft
    input:
      name: "${input.name}"

  - id: approve_draft
    kind: human
    input:
      draft: "${nodes.create_draft.output}"
    reviewers:
      - reviewers
    next: finish

  - id: finish
    kind: output
    value:
      message: "${nodes.approve_draft.output.message}"
      approved: true
""",
    }


def _render_test(*, name: str, workflow_dir: Path) -> str:
    workflow = workflow_dir / "workflow.yaml"
    input_file = workflow_dir / "input.json"
    return f"""from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wf.compiler import compile_file
from wf.runtime import WorkflowRuntime
from wf.validate import validate_ir


class {''.join(part.capitalize() for part in name.split('_'))}WorkflowTests(unittest.TestCase):
    def test_generated_workflow_runs(self) -> None:
        ir = compile_file({str(workflow)!r})
        validate_ir(ir)
        payload = json.loads(Path({str(input_file)!r}).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)
        self.assertIsInstance(result.output, dict)


if __name__ == "__main__":
    unittest.main()
"""
