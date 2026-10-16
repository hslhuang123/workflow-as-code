from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wf.compiler import compile_file, read_ir, write_ir
from wf.providers import PROVIDER_NAMES, create_provider
from wf.scaffold import TEMPLATES, init_workflow
from wf.inspect import doctor_workflow, format_workflow_list, graph_workflow, list_workflows, load_workflow, describe_workflow
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

    init_parser = sub.add_parser("init", help="create a new workflow folder from a template")
    init_parser.add_argument("name", help="workflow name")
    init_parser.add_argument("--template", default="basic", choices=TEMPLATES, help="workflow template")
    init_parser.add_argument("--dir", default="examples", help="destination directory")
    init_parser.add_argument("--force", action="store_true", help="replace an existing workflow folder")
    init_parser.add_argument("--with-test", action="store_true", help="generate a unittest file")

    list_parser = sub.add_parser("list", help="list workflows")
    list_parser.add_argument("--dir", default="examples", help="directory to search")
    list_parser.add_argument("--json", action="store_true", help="emit JSON")

    describe_parser = sub.add_parser("describe", help="describe a workflow")
    describe_parser.add_argument("path", help="workflow YAML path or IR JSON with --ir")
    describe_parser.add_argument("--ir", action="store_true", help="treat path as compiled IR JSON")
    describe_parser.add_argument("--json", action="store_true", help="emit JSON")

    graph_parser = sub.add_parser("graph", help="print workflow graph")
    graph_parser.add_argument("path", help="workflow YAML path or IR JSON with --ir")
    graph_parser.add_argument("--ir", action="store_true", help="treat path as compiled IR JSON")
    graph_parser.add_argument("--format", choices=("mermaid", "dot"), default="mermaid", help="graph output format")
    graph_parser.add_argument("--out", help="write graph to file")

    doctor_parser = sub.add_parser("doctor", help="debug workflow setup")
    doctor_parser.add_argument("path", help="workflow YAML path")
    doctor_parser.add_argument("--input", help="optional input JSON path for a real run")
    doctor_parser.add_argument("--auto-approve", action="store_true", help="auto-approve human nodes")
    doctor_parser.add_argument("--run-root", default="runs", help="directory for run traces")
    doctor_parser.add_argument("--provider", default="fake", choices=PROVIDER_NAMES, help="agent provider")
    doctor_parser.add_argument("--model", default=None, help="provider model override")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            ir = read_ir(args.path) if args.ir else compile_file(args.path)
            validate_ir(ir, source=args.path)
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
        if args.command == "init":
            result = init_workflow(
                args.name,
                template=args.template,
                base_dir=args.dir,
                force=args.force,
                with_test=args.with_test,
            )
            print(f"created workflow: {result.name}")
            print(f"directory: {result.directory}")
            print(f"workflow: {result.workflow_path}")
            print(f"input: {result.input_path}")
            if result.test_path:
                print(f"test: {result.test_path}")
            return 0
        if args.command == "list":
            print(format_workflow_list(list_workflows(args.dir), as_json=args.json))
            return 0
        if args.command == "describe":
            ir = load_workflow(args.path, is_ir=args.ir)
            print(describe_workflow(ir, as_json=args.json))
            return 0
        if args.command == "graph":
            ir = load_workflow(args.path, is_ir=args.ir)
            output = graph_workflow(ir, output_format=args.format)
            if args.out:
                Path(args.out).write_text(output + "\n", encoding="utf-8")
            else:
                print(output)
            return 0
        if args.command == "doctor":
            ok, output = doctor_workflow(
                args.path,
                input_path=args.input,
                provider=args.provider,
                auto_approve=args.auto_approve,
                model=args.model,
                run_root=args.run_root,
            )
            print(output)
            return 0 if ok else 1
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
