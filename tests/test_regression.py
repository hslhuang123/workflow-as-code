from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wf.cli import main as cli_main
from wf.compiler import compile_file, write_ir
from wf.ir import Node
from wf.providers import PROVIDER_NAMES, create_provider
from wf.providers.anthropic import AnthropicAgentProvider, AnthropicProviderError, FuelIXAgentProvider
from wf.registries import Registries, ValidationError
from wf.runtime import WorkflowRuntime
from wf.trace import TraceError, format_trace
from wf.validate import WorkflowValidationError, validate_ir
from wf.scaffold import ScaffoldError, init_workflow, normalize_name


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
                "message": "Order accepted for Nova",
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

    def test_validation_diagnostics_include_hints_and_path(self) -> None:
        source = Path("examples/restaurant_takeout/workflow.yaml").read_text(encoding="utf-8")
        cases = {
            "unknown_task": (
                source.replace("uses: calculate_total", "uses: calcualte_total"),
                ["unknown task 'calcualte_total'", "did you mean 'calculate_total'?"],
            ),
            "missing_case_target": (
                source.replace("valid: calculate_total", "valid: calculate_totl"),
                ["case 'valid' targets missing node 'calculate_totl'", "did you mean 'calculate_total'?", "existing nodes:", "finish_rejected"],
            ),
            "bad_expression": (
                source.replace("${input.customer_name}", "${customer_name}"),
                ["unsupported expression ${customer_name}", "${input.field}", "${nodes.node_id.output.field}"],
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (text, expected) in cases.items():
                with self.subTest(name):
                    path = Path(tmp) / f"{name}.yaml"
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(Exception) as error:
                        compile_file(path)
                    message = str(error.exception)
                    self.assertIn(f"workflow validation failed: {path}", message)
                    for fragment in expected:
                        self.assertIn(fragment, message)

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
                WorkflowRuntime(missing_ir, run_root=tmp).run({"customer_name": "Nova", "items": ["burger"]}, auto_approve=True)
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
            self.assertIn("Order accepted for Nova", stdout.getvalue())
            self.assertIn("finish_accepted", stdout.getvalue())
            self.assertIn("trace:", stderr.getvalue())
            run_dirs = [path for path in Path(tmp).iterdir() if path.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            for filename in ["input.json", "output.json", "trace.jsonl", "workflow.ir.json", "summary.json"]:
                self.assertTrue((run_dir / filename).exists(), filename)
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "succeeded")
            self.assertEqual(summary["workflow"], "restaurant_takeout")

    def test_list_reports_invalid_workflow_concisely_and_json_keeps_detail(self) -> None:
        source = Path("examples/restaurant_takeout/workflow.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad" / "workflow.yaml"
            bad.parent.mkdir()
            bad.write_text(source.replace("uses: calculate_total", "uses: calcualte_total"), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(cli_main(["list", "--dir", tmp]), 0)
            text = stdout.getvalue()
            self.assertIn("invalid", text)
            self.assertIn("unknown task 'calcualte_total'", text)
            self.assertEqual(len(text.strip().splitlines()), 1)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                cli_main(["list", "--dir", tmp, "--json"])
            item = json.loads(stdout.getvalue())[0]
            self.assertEqual(item["status"], "invalid")
            self.assertIn("did you mean 'calculate_total'?", item["error"])

    def test_cli_list_describe_graph_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(cli_main(["list", "--dir", "examples"]), 0)
            self.assertIn("restaurant_takeout", stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(cli_main(["describe", "examples/restaurant_takeout/workflow.yaml"]), 0)
            self.assertIn("Workflow: restaurant_takeout", stdout.getvalue())
            self.assertIn("route_order_status", stdout.getvalue())

            graph_path = Path(tmp) / "graph.mmd"
            self.assertEqual(cli_main(["graph", "examples/restaurant_takeout/workflow.yaml", "--out", str(graph_path)]), 0)
            graph = graph_path.read_text(encoding="utf-8")
            self.assertIn("flowchart TD", graph)
            self.assertIn("route_order_status -->|valid| calculate_total", graph)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(cli_main([
                    "doctor",
                    "examples/restaurant_takeout/workflow.yaml",
                    "--input",
                    "examples/restaurant_takeout/input.json",
                    "--run-root",
                    tmp,
                ]), 0)
            self.assertIn("[ok] validate", stdout.getvalue())
            self.assertIn("[ok] run", stdout.getvalue())

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
        self.assertIn("Classification object", captured["system"])
        self.assertIn("category", captured["system"])
        self.assertIn("confidence", captured["system"])
        self.assertIn("rationale", captured["system"])

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
        self.assertIn("Classification object", captured["system"])
        self.assertIn("confidence", captured["system"])
        self.assertIn("rationale", captured["system"])

    def test_fuelix_provider_registered_in_factory(self) -> None:
        self.assertIn("fuelix", PROVIDER_NAMES)
        provider = create_provider("fuelix", model="fuelix-model")
        self.assertIsInstance(provider, FuelIXAgentProvider)
        self.assertEqual(provider.model, "fuelix-model")

    def test_fuelix_http_transport_headers(self) -> None:
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self) -> bytes:
                return b'{"content": []}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = {key.lower(): value for key, value in request.header_items()}
            captured["timeout"] = timeout
            return Response()

        provider = FuelIXAgentProvider(api_key="fuelix-test", api_url="https://api.fuelix.ai/v1/messages")
        with patch("urllib.request.urlopen", fake_urlopen):
            provider._http_transport({"model": "test", "messages": [], "max_tokens": 1})

        self.assertEqual(captured["url"], "https://api.fuelix.ai/v1/messages")
        self.assertEqual(captured["headers"]["authorization"], "Bearer fuelix-test")
        self.assertEqual(captured["headers"]["user-agent"], "workflow-as-code/0.1.0")
        self.assertEqual(captured["headers"]["accept"], "application/json")
        self.assertEqual(captured["timeout"], 60)

    def test_scaffold_basic_workflow_runs(self) -> None:
        base = Path("tmp_scaffold_tests")
        shutil.rmtree(base, ignore_errors=True)
        try:
            result = init_workflow("Hello World", base_dir=base, with_test=True)
            self.assertEqual(result.name, "hello_world")
            ir = compile_file(result.workflow_path)
            payload = json.loads(result.input_path.read_text(encoding="utf-8"))
            with tempfile.TemporaryDirectory() as tmp:
                run = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)
            self.assertEqual(run.output, {"message": "Welcome aboard, Nova — your workflow is running!"})
            self.assertTrue((Path("tests") / "test_hello_world.py").exists())
        finally:
            shutil.rmtree(base, ignore_errors=True)
            (Path("tests") / "test_hello_world.py").unlink(missing_ok=True)

    def test_scaffold_templates_validate_and_run(self) -> None:
        base = Path("tmp_scaffold_templates")
        shutil.rmtree(base, ignore_errors=True)
        try:
            for template in ("basic", "router", "agent", "human"):
                result = init_workflow(f"demo_{template}", template=template, base_dir=base)
                ir = compile_file(result.workflow_path)
                validate_ir(ir)
                payload = json.loads(result.input_path.read_text(encoding="utf-8"))
                with tempfile.TemporaryDirectory() as tmp:
                    run = WorkflowRuntime(ir, run_root=tmp).run(payload, auto_approve=True)
                self.assertIsInstance(run.output, dict)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_scaffold_name_safety_and_force(self) -> None:
        self.assertEqual(normalize_name("Pizza Order"), "pizza_order")
        with self.assertRaises(ScaffoldError):
            normalize_name("../bad")
        base = Path("tmp_scaffold_force")
        shutil.rmtree(base, ignore_errors=True)
        try:
            init_workflow("Pizza Order", base_dir=base)
            with self.assertRaises(ScaffoldError):
                init_workflow("pizza_order", base_dir=base)
            init_workflow("pizza_order", base_dir=base, force=True)
            self.assertTrue((base / "pizza_order" / "workflow.yaml").exists())
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_scaffold_cli_init(self) -> None:
        base = Path("tmp_scaffold_cli")
        shutil.rmtree(base, ignore_errors=True)
        try:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(cli_main(["init", "CLI Demo", "--dir", str(base), "--template", "basic"]), 0)
            self.assertIn("created workflow: cli_demo", stdout.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli_main(["validate", str(base / "cli_demo" / "workflow.yaml")]), 0)
        finally:
            shutil.rmtree(base, ignore_errors=True)



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
