from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wf.compiler import compile_file, read_ir, write_ir
from wf.runtime import WorkflowRuntime
from wf.validate import validate_ir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wf")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="validate a workflow YAML file or IR JSON file")
    validate_parser.add_argument("path")
    validate_parser.add_argument("--ir", action="store_true", help="treat path as compiled IR JSON")

    compile_parser = sub.add_parser("compile", help="compile workflow YAML to JSON IR")
    compile_parser.add_argument("path")
    compile_parser.add_argument("--out", required=True)

    run_parser = sub.add_parser("run", help="run compiled JSON IR")
    run_parser.add_argument("path")
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--auto-approve", action="store_true", help="auto-approve human nodes for local smoke runs")
    run_parser.add_argument("--run-root", default="runs")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            ir = read_ir(args.path) if args.ir else compile_file(args.path)
            validate_ir(ir)
            print(f"valid: {ir.name} ({len(ir.nodes)} nodes)")
            return 0
        if args.command == "compile":
            ir = compile_file(args.path)
            write_ir(ir, args.out)
            print(f"compiled: {args.path} -> {args.out}")
            return 0
        if args.command == "run":
            ir = read_ir(args.path)
            input_payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = WorkflowRuntime(ir, run_root=args.run_root).run(input_payload, auto_approve=args.auto_approve)
            print(json.dumps(result.output, indent=2, sort_keys=True))
            print(f"trace: {result.trace_path}", file=sys.stderr)
            return 0
        raise AssertionError(args.command)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
