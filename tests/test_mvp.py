from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wf.compiler import compile_file, write_ir
from wf.runtime import WorkflowRuntime
from wf.validate import validate_ir


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


if __name__ == "__main__":
    unittest.main()
