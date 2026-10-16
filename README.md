# Workflow as Code

A local workflow-as-code MVP. Define workflows in YAML, compile them into a JSON intermediate representation, and run them with a Python runtime.

## What this project does

The MVP proves this flow:

```text
workflow.yaml -> compile -> build/*.ir.json -> run -> trace.jsonl
```

Supported node kinds:

| Kind | Purpose |
|---|---|
| `task` | Run a deterministic Python function from a task registry |
| `agent` | Run an LLM-style node through the provider interface; currently backed by a deterministic fake provider |
| `router` | Route to another node based on prior output |
| `human` | Pause for approval; local smoke runs can use `--auto-approve` |
| `output` | Produce final workflow output |

## Requirements

- Python 3.10+
- No required third-party Python packages for the current MVP

Commands below assume you are at the repository root.

## Quick start

Validate the restaurant workflow:

```bash
PYTHONPATH=src:. python -m wf.cli validate examples/restaurant_takeout/workflow.yaml
```

Compile it:

```bash
PYTHONPATH=src:. python -m wf.cli compile \
  examples/restaurant_takeout/workflow.yaml \
  --out build/restaurant_takeout.ir.json
```

Run it:

```bash
PYTHONPATH=src:. python -m wf.cli run \
  build/restaurant_takeout.ir.json \
  --input examples/restaurant_takeout/input.json
```

Expected output with the current sample input:

```json
{
  "message": "Order accepted for Michael",
  "status": "accepted",
  "total": 21.77
}
```

Run all tests:

```bash
PYTHONPATH=src:. python -m unittest discover -s tests
```

## Optional editable install

Instead of setting `PYTHONPATH` every time:

```bash
python -m pip install -e .
```

Then use:

```bash
wf validate examples/restaurant_takeout/workflow.yaml
wf compile examples/restaurant_takeout/workflow.yaml --out build/restaurant_takeout.ir.json
wf run build/restaurant_takeout.ir.json --input examples/restaurant_takeout/input.json
```

## Workflow folder structure

Each workflow example uses this shape:

```text
examples/<workflow_name>/
  __init__.py
  workflow.yaml
  input.json
  schemas.py
  tasks.py
  tools.py
```

Meaning:

| File | Purpose |
|---|---|
| `workflow.yaml` | Workflow graph: nodes, routing, registries, input/output schemas |
| `input.json` | Sample runtime input |
| `schemas.py` | Dataclass contracts used by validation/runtime |
| `tasks.py` | Deterministic task functions referenced by `uses:` |
| `tools.py` | Agent tool registry, or placeholder when unused |
| `__init__.py` | Makes the folder importable |

## Example workflows

| Folder | Workflow name | Purpose |
|---|---|---|
| `examples/restaurant_takeout/` | `restaurant_takeout` | Validates takeout items and calculates total |
| `examples/exchange/` | `exchange` | Converts money using deterministic exchange-rate tasks |
| `examples/test_workflow/` | `test_triage` | Classifies a test message and routes refund through exchange steps |
| `examples/support/` | `support_triage` | Support-ticket triage with agent and human approval nodes |

## Build a new workflow

1. Create a folder:

```bash
mkdir -p examples/my_workflow
touch examples/my_workflow/__init__.py
```

2. Add data contracts in `schemas.py`.
3. Add deterministic functions in `tasks.py`.
4. Add tools in `tools.py`, or a placeholder docstring if unused.
5. Add sample input in `input.json`.
6. Add graph wiring in `workflow.yaml`.
7. Validate, compile, run.
8. Add a test in `tests/test_mvp.py`.

## IR

IR means **Intermediate Representation**. In this project, it is the compiled JSON workflow graph used by the runtime.

Example:

```text
examples/restaurant_takeout/workflow.yaml
  -> build/restaurant_takeout.ir.json
  -> runtime execution
```

The concept is standard in compilers and systems. The JSON schema here is project-specific.

## Traces

Every run writes a trace file:

```text
runs/<run_id>/trace.jsonl
```

Inspect it with:

```bash
cat runs/<run_id>/trace.jsonl
```

Each line records one executed node, including node id, kind, status, output summary, and routing choices.

## Current limitations

- No hosted service.
- No visual builder.
- No real LLM provider wired into CLI selection yet.
- No durable multi-day execution.
- No parallel branches or sub-workflows.
- The YAML loader supports only the subset needed by this MVP.
- Money calculations in examples use floats; production money logic should use `Decimal`.
