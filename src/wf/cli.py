from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wf.compiler import compile_file, read_ir, write_ir
from wf.providers import PROVIDER_NAMES, create_provider
from wf.runtime import WorkflowRuntime
from wf.trace import format_trace, latest_trace
from wf.validate import validate_ir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wf")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="validate a workflow YAML file or IR JSON file")
    validate_parser.add_argument("path", help="workflow YAML path, or IR JSON path with --ir")
    validate_parser.add_argument("--ir", action="store_true", help="treat path as compiled IR JSON")

    compile_parser = sub.add_parser("compile", help="compile workflow YAML to JSON IR")
    compile_parser.add_argument("path", help="workflow YAML path")
    compile_parser.add_argument("--out", required=True, help="output IR JSON path")

    run_parser = sub.add_parser("run", help="run compiled JSON IR")
    _add_run_args(run_parser, path_help="compiled IR JSON path")

    run_yaml_parser = sub.add_parser("run-yaml", help="validate, compile in memory, and run workflow YAML")
    _add_run_args(run_yaml_parser, path_help="workflow YAML path")

    trace_parser = sub.add_parser("trace", help="print a human-readable trace")
    trace_parser.add_argument("path", nargs="?", help="trace JSONL path")
    trace_parser.add_argument("--latest", action="store_true", help="use latest runs/*/trace.jsonl")
    trace_parser.add_argument("--run-root", default="runs", help="run directory for --latest")

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
            return _run_ir(ir, args)
        if args.command == "run-yaml":
            ir = compile_file(args.path)
            return _run_ir(ir, args)
        if args.command == "trace":
            if args.latest:
                path = latest_trace(args.run_root)
            elif args.path:
                path = Path(args.path)
            else:
                raise ValueError("trace requires a path or --latest")
            print(format_trace(path))
            return 0
        raise AssertionError(args.command)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _add_run_args(parser: argparse.ArgumentParser, *, path_help: str) -> None:
    parser.add_argument("path", help=path_help)
    parser.add_argument("--input", required=True, help="input JSON path")
    parser.add_argument("--auto-approve", action="store_true", help="auto-approve human nodes for local smoke runs")
    parser.add_argument("--run-root", default="runs", help="directory for run traces")
    parser.add_argument("--provider", default="fake", choices=PROVIDER_NAMES, help="agent provider")
    parser.add_argument("--model", default=None, help="provider model override")


def _run_ir(ir, args: argparse.Namespace) -> int:
    input_payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    provider = create_provider(args.provider, model=args.model)
    result = WorkflowRuntime(ir, provider=provider, run_root=args.run_root).run(
        input_payload,
        auto_approve=args.auto_approve,
    )
    print(json.dumps(result.output, indent=2, sort_keys=True))
    print(f"run_id: {result.run_id}", file=sys.stderr)
    print(f"trace: {result.trace_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
