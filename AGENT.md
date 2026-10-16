# Agent Guide

## Project purpose

This repository is a local workflow-as-code MVP. Users define workflows in YAML, compile them into JSON IR, and run the compiled IR with a Python runtime.

The current MVP supports:

- deterministic task nodes
- fake deterministic agent nodes for tests and demos
- router nodes
- human approval nodes with `--auto-approve`
- output nodes
- local trace files under `runs/<run_id>/trace.jsonl`

## Repository layout

```text
docs/
  PLAN.md
  MVP.md
src/wf/
  cli.py
  compiler.py
  expressions.py
  ir.py
  registries.py
  runtime.py
  validate.py
  yaml_loader.py
  providers/
  backends/
examples/
  exchange/
  restaurant_takeout/
  support/
  test_workflow/
tests/
  test_mvp.py
```

## Workflow folder convention

Each workflow example lives in one folder:

```text
examples/<workflow_name>/
  __init__.py
  workflow.yaml
  input.json
  schemas.py
  tasks.py
  tools.py
```

Rules:

- `workflow.yaml` defines the graph.
- `schemas.py` defines dataclass contracts.
- `tasks.py` defines deterministic task functions.
- `tools.py` defines agent-callable tools, or a placeholder if unused.
- `input.json` is a sample payload.
- One YAML file defines one workflow.

## Commands

Run commands from the repository root.

Create a virtual environment and install CLI for local use:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Validate a workflow:

```bash
wf validate examples/restaurant_takeout/workflow.yaml
```

Compile YAML to IR:

```bash
wf compile examples/restaurant_takeout/workflow.yaml --out build/restaurant_takeout.ir.json
```

Run compiled IR:

```bash
wf run build/restaurant_takeout.ir.json --input examples/restaurant_takeout/input.json
```

Run YAML directly:

```bash
wf run-yaml examples/restaurant_takeout/workflow.yaml --input examples/restaurant_takeout/input.json
```

Inspect traces:

```bash
wf trace --latest
```

Run tests:

```bash
python -m unittest discover -s tests
```

## Implementation notes

- Avoid adding dependencies unless needed. The current YAML loader is dependency-free and intentionally minimal.
- The runtime reads compiled IR JSON for `wf run`; `wf run-yaml` compiles in memory.
- Keep workflow YAML declarative. Put executable business logic in `tasks.py` or `tools.py`.
- Keep task functions deterministic. LLM or reasoning behavior belongs in `agent` nodes.
- Preserve fake provider behavior for deterministic tests.
- Anthropic provider behavior must stay isolated behind the provider interface and covered by stubbed transport tests.
- Provider names are `fake`, `anthropic`, and `fuelix`; keep provider adapters behind `wf.providers.create_provider`.
- Fuel iX uses the Anthropic-compatible provider path with `FUELIX_API_KEY` or `ANTHROPIC_AUTH_TOKEN`.
- When adding a workflow, add a test in `tests/test_mvp.py` that compiles and runs it.

## Current example workflows

| Workflow folder | Workflow name | Purpose |
|---|---|---|
| `examples/exchange/` | `exchange` | Currency conversion |
| `examples/restaurant_takeout/` | `restaurant_takeout` | Takeout order validation and pricing |
| `examples/support/` | `support_triage` | Support-ticket triage with agent/human nodes |
| `examples/test_workflow/` | `test_triage` | Small routing workflow with exchange step |

## Verification expectation

Before handing off changes, run the smallest relevant smoke command and the affected test. For broad workflow/runtime changes, run:

```bash
python -m unittest discover -s tests
```
