from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from wf.cli import main as cli_main
from wf.compiler import compile_file, write_ir
from wf.ir import Node
from wf.providers import PROVIDER_NAMES, create_provider
from wf.providers.anthropic import AnthropicAgentProvider, AnthropicProviderError, FuelIXAgentProvider
from wf.registries import Registries, ValidationError
from wf.runtime import WorkflowRuntime
from wf.trace import TraceError, format_trace
from wf.validate import WorkflowValidationError, validate_ir


class MvpTests(unittest.TestCase):
    def test_validate_and_compile_support_workflow(self) -> None:
        ir = compile_file("examples/support/workflow.yaml")
        validate_ir(ir)
        self.assertEqual(ir.name, "support_triage")
        self.assertEqual({node.kind for node in ir.nodes}, {"task", "agent", "router", "human", "output"})

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "support_triage.ir.json"
            write_ir(ir, out)
            first = out.read_text(encoding="utf-8")
            write_ir(ir, out)
            self.assertEqual(out.read_text(encoding="utf-8"), first)

    def test_run_refund_path_with_auto_approval(self) -> None:
        ir = compile_file("examples/support/workflow.yaml")
        payload = json.loads(Path("examples/support/input.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)

            self.assertEqual(result.output, {
                "ticket_id": "ticket_refund_123",
                "category": "refund",
                "reply_sent": True,
                "escalated": False,
            })
            trace = result.trace_path.read_text(encoding="utf-8")
            self.assertIn("approve_refund_reply", trace)
            self.assertIn("send_refund_reply", trace)

    def test_run_bug_path(self) -> None:
        ir = compile_file("examples/support/workflow.yaml")
        payload = json.loads(Path("examples/support/input_bug.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)

            self.assertEqual(result.output, {
                "ticket_id": "ticket_bug_456",
                "category": "bug",
                "reply_sent": False,
                "escalated": True,
            })
            trace = result.trace_path.read_text(encoding="utf-8")
            self.assertIn("escalate_bug", trace)

    def test_test_workflow_refund_route(self) -> None:
        ir = compile_file("examples/test_workflow/workflow.yaml")
        payload = json.loads(Path("examples/test_workflow/input.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)

            self.assertEqual(result.output, {
                "category": "refund",
                "handled_by": "billing",
                "message": "Refund path selected for test_ticket_001: converted 100.0 USD to 92.0 EUR",
            })
            trace = result.trace_path.read_text(encoding="utf-8")
            self.assertIn("get_exchange_rate", trace)
            self.assertIn("convert_amount", trace)
            self.assertIn("finish_refund", trace)
            self.assertNotIn("finish_default", trace)

    def test_exchange_workflow(self) -> None:
        ir = compile_file("examples/exchange/workflow.yaml")
        validate_ir(ir)
        payload = json.loads(Path("examples/exchange/input.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)

            self.assertEqual(result.output, {
                "original_amount": 100.0,
                "converted_amount": 92.0,
                "from_currency": "USD",
                "to_currency": "EUR",
                "rate": 0.92,
                "message": "Converted 100.0 USD to 92.0 EUR",
            })
            trace = result.trace_path.read_text(encoding="utf-8")
            self.assertIn("get_exchange_rate", trace)
            self.assertIn("convert_amount", trace)
            self.assertIn("finish_exchange", trace)

    def test_restaurant_takeout_valid_order(self) -> None:
        ir = compile_file("examples/restaurant_takeout/workflow.yaml")
        validate_ir(ir)
        payload = json.loads(Path("examples/restaurant_takeout/input.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)

            self.assertEqual(result.output, {
                "status": "accepted",
                "message": "Order accepted for Michael",
                "total": 21.77,
            })

            trace = result.trace_path.read_text(encoding="utf-8")
            self.assertIn("create_order", trace)
            self.assertIn("check_menu_items", trace)
            self.assertIn("calculate_total", trace)
            self.assertIn("finish_accepted", trace)
            self.assertNotIn("finish_rejected", trace)

    def test_restaurant_takeout_invalid_order_routes_to_rejected(self) -> None:
        ir = compile_file("examples/restaurant_takeout/workflow.yaml")
        payload = json.loads(Path("examples/restaurant_takeout/input_invalid.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)

            self.assertEqual(result.output, {
                "status": "rejected",
                "message": "Order rejected because some items are unavailable",
                "total": 0.0,
            })
            trace = result.trace_path.read_text(encoding="utf-8")
            self.assertIn("finish_rejected", trace)
            self.assertNotIn("calculate_total", trace)

    def test_validation_failure_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unknown_task = root / "unknown_task.yaml"
            unknown_task.write_text(_workflow_yaml(task_uses="missing_task"), encoding="utf-8")
            with self.assertRaises(WorkflowValidationError) as task_error:
                compile_file(unknown_task)
            self.assertIn("unknown task", str(task_error.exception))
            self.assertIn("missing_task", str(task_error.exception))

            missing_schema = root / "missing_schema.yaml"
            missing_schema.write_text(_workflow_yaml(input_schema="MissingInput"), encoding="utf-8")
            with self.assertRaises(WorkflowValidationError) as schema_error:
                compile_file(missing_schema)
            self.assertIn("unknown input schema", str(schema_error.exception))
            self.assertIn("MissingInput", str(schema_error.exception))

            unreachable = root / "unreachable.yaml"
            unreachable.write_text(_workflow_yaml(extra_output=True), encoding="utf-8")
            with self.assertRaises(WorkflowValidationError) as unreachable_error:
                compile_file(unreachable)
            self.assertIn("unreachable nodes", str(unreachable_error.exception))
            self.assertIn("unused_output", str(unreachable_error.exception))

    def test_runtime_failure_contracts(self) -> None:
        ir = compile_file("examples/restaurant_takeout/workflow.yaml")
        with self.assertRaises(ValidationError) as input_error:
            WorkflowRuntime(ir).run({"customer_name": 123, "items": ["burger"]}, auto_approve=True)
        self.assertIn("input.customer_name", str(input_error.exception))
        self.assertIn("expected str", str(input_error.exception))

        with tempfile.TemporaryDirectory() as tmp:
            missing_input = Path(tmp) / "missing_task_input.yaml"
            missing_input.write_text(_workflow_yaml(omit_customer_name=True), encoding="utf-8")
            missing_ir = compile_file(missing_input)
            with self.assertRaises(ValidationError) as task_input_error:
                WorkflowRuntime(missing_ir, run_root=tmp).run({"customer_name": "Michael", "items": ["burger"]}, auto_approve=True)
            self.assertIn("node create_order", str(task_input_error.exception))
            self.assertIn("missing inputs: customer_name", str(task_input_error.exception))

    def test_cli_run_yaml_and_trace_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(cli_main([
                    "run-yaml",
                    "examples/restaurant_takeout/workflow.yaml",
                    "--input",
                    "examples/restaurant_takeout/input.json",
                    "--run-root",
                    tmp,
                ]), 0)
                self.assertEqual(cli_main(["trace", "--latest", "--run-root", tmp]), 0)
            self.assertIn("Order accepted for Michael", stdout.getvalue())
            self.assertIn("finish_accepted", stdout.getvalue())
            self.assertIn("trace:", stderr.getvalue())

    def test_trace_malformed_json_reports_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            trace.write_text('{"node_id": "ok", "kind": "task", "status": "succeeded"}\n{bad}\n', encoding="utf-8")
            with self.assertRaises(TraceError) as error:
                format_trace(trace)
            self.assertIn("line 2", str(error.exception))

    def test_invalid_provider_name_rejected_by_cli(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                cli_main([
                    "run-yaml",
                    "examples/restaurant_takeout/workflow.yaml",
                    "--input",
                    "examples/restaurant_takeout/input.json",
                    "--provider",
                    "bogus",
                ])
        self.assertNotEqual(error.exception.code, 0)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_anthropic_provider_contract_valid_output(self) -> None:
        captured: dict[str, object] = {}

        def transport(payload: dict[str, object]) -> dict[str, object]:
            captured.update(payload)
            return {
                "content": [{"type": "text", "text": '{"category":"bug","confidence":0.8,"rationale":"stub"}'}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

        provider = AnthropicAgentProvider(api_key="test", model="test-model", transport=transport)
        registries = Registries.load({
            "tasks": "examples.support.tasks",
            "tools": "examples.support.tools",
            "schemas": "examples.support.schemas",
        })
        node = Node(
            id="classify_ticket",
            kind="agent",
            model="ignored",
            instructions="Classify.",
            input={},
            output_schema="Classification",
            tools=["search_knowledge_base"],
            policy={"max_steps": 2, "max_tokens": 100},
        )

        result = provider.run_agent(node=node, inputs={"ticket": {"subject": "Bug", "body": "broken"}}, registries=registries)

        self.assertEqual(result.output["category"], "bug")
        self.assertEqual(result.tokens, 15)
        self.assertEqual(captured["model"], "test-model")
        self.assertEqual(captured["tools"][0]["name"], "search_knowledge_base")
        self.assertIn("Classify", captured["system"])

    def test_anthropic_provider_rejects_invalid_json_and_undeclared_tool(self) -> None:
        registries = Registries.load({
            "tasks": "examples.support.tasks",
            "tools": "examples.support.tools",
            "schemas": "examples.support.schemas",
        })
        node = Node(
            id="classify_ticket",
            kind="agent",
            instructions="Classify.",
            output_schema="Classification",
            tools=[],
            policy={"max_steps": 1},
        )

        invalid_json_provider = AnthropicAgentProvider(
            api_key="test",
            transport=lambda payload: {"content": [{"type": "text", "text": "not json"}]},
        )
        with self.assertRaises(AnthropicProviderError) as json_error:
            invalid_json_provider.run_agent(node=node, inputs={}, registries=registries)
        self.assertIn("invalid JSON", str(json_error.exception))

        undeclared_tool_provider = AnthropicAgentProvider(
            api_key="test",
            transport=lambda payload: {
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "search_knowledge_base", "input": {"query": "refund"}}
                ]
            },
        )
        with self.assertRaises(AnthropicProviderError) as tool_error:
            undeclared_tool_provider.run_agent(node=node, inputs={}, registries=registries)
        self.assertIn("undeclared tool", str(tool_error.exception))

    def test_fuelix_provider_contract_valid_output(self) -> None:
        captured: dict[str, object] = {}

        def transport(payload: dict[str, object]) -> dict[str, object]:
            captured.update(payload)
            return {
                "content": [{"type": "text", "text": '{"category":"refund","confidence":0.9,"rationale":"stub"}'}],
                "usage": {"input_tokens": 8, "output_tokens": 7},
            }

        provider = FuelIXAgentProvider(api_key="fuelix-test", model="fuelix-model", transport=transport)
        registries = Registries.load({
            "tasks": "examples.support.tasks",
            "tools": "examples.support.tools",
            "schemas": "examples.support.schemas",
        })
        node = Node(
            id="classify_ticket",
            kind="agent",
            instructions="Classify.",
            output_schema="Classification",
            tools=["search_knowledge_base"],
            policy={"max_steps": 2, "max_tokens": 100},
        )

        result = provider.run_agent(node=node, inputs={"ticket": {"subject": "Refund", "body": "charged"}}, registries=registries)

        self.assertEqual(result.output["category"], "refund")
        self.assertEqual(result.tokens, 15)
        self.assertEqual(captured["model"], "fuelix-model")
        self.assertEqual(captured["tools"][0]["name"], "search_knowledge_base")

    def test_fuelix_provider_registered_in_factory(self) -> None:
        self.assertIn("fuelix", PROVIDER_NAMES)
        provider = create_provider("fuelix", model="fuelix-model")
        self.assertIsInstance(provider, FuelIXAgentProvider)
        self.assertEqual(provider.model, "fuelix-model")



def _workflow_yaml(
    *,
    task_uses: str = "create_order",
    input_schema: str = "TakeoutInput",
    extra_output: bool = False,
    omit_customer_name: bool = False,
) -> str:
    customer_line = "" if omit_customer_name else '      customer_name: "${input.customer_name}"\n'
    extra = """

  - id: unused_output
    kind: output
    value:
      status: unused
      message: unused
      total: 0.0
""" if extra_output else ""
    return f'''name: bad_restaurant
version: 0.1.0

input_schema: {input_schema}
output_schema: TakeoutResult

registries:
  tasks: examples.restaurant_takeout.tasks
  tools: examples.restaurant_takeout.tools
  schemas: examples.restaurant_takeout.schemas

nodes:
  - id: create_order
    kind: task
    uses: {task_uses}
    input:
{customer_line}      items: "${{input.items}}"

  - id: finish
    kind: output
    value:
      status: accepted
      message: ok
      total: 0.0
{extra}'''
if __name__ == "__main__":
    unittest.main()
