# Workflow-as-Code Platform: MVP Plan

## Goal

Build the smallest useful workflow-as-code system that proves the core bet: a workflow designer can define a typed graph with deterministic tasks, explicit LLM agent nodes, routing, and human approval; the platform validates it and runs it through one backend.

The MVP is not a hosted product. It is a local developer tool plus a backend runtime spike that can run one real workflow end to end.

## Target user

Primary MVP user: a technical workflow builder who may not be a Python expert.

Implication: the MVP should use a YAML workflow definition as the first authoring format, with task/tool implementations registered from Python modules. A Python SDK can come later once the IR is stable.

## Core decisions

| Decision | MVP choice | Reason |
|---|---|---|
| Authoring format | YAML | Easier for non-Python workflow designers and reviewable in Git |
| Canonical internal format | JSON IR | Stable machine contract between authoring and runtime |
| Runtime backend | LangGraph | Fastest path to agent routing/checkpoint spike |
| Custom code | Python task/tool registry | Keeps YAML declarative; avoids inline code execution |
| Agent behavior | Instructions + typed inputs/outputs + tools + policy | Explicit, auditable, validateable |
| UI | None | CLI proves the model first |
| Persistence | Local run state only | Enough for MVP; durable execution is later |

## MVP user story

A user can write this workflow:

1. Receive a support ticket input.
2. Fetch ticket details with a deterministic task.
3. Classify the ticket with an LLM agent.
4. Route by category.
5. For refund cases, pause for human approval.
6. Draft and send a reply.
7. Emit a structured final result.

They can then run:

```bash
wf validate workflows/support_triage.yaml
wf compile workflows/support_triage.yaml --out build/support_triage.ir.json
wf run build/support_triage.ir.json --input examples/ticket.json
```

## MVP workflow definition example

```yaml
name: support_triage
version: 0.1.0

input_schema: TicketInput
output_schema: TriageResult

registries:
  tasks: examples.support.tasks
  tools: examples.support.tools
  schemas: examples.support.schemas

nodes:
  - id: fetch_ticket
    kind: task
    uses: fetch_ticket
    input:
      ticket_id: "${input.ticket_id}"
    retry:
      max_attempts: 3
    timeout_seconds: 10

  - id: classify_ticket
    kind: agent
    model: claude-sonnet-5-5
    instructions: |
      Classify the customer support ticket.

      Categories:
      - refund: customer asks for money back, cancellation, or compensation
      - bug: product appears broken
      - billing: invoices, payment methods, taxes, receipts, failed charges
      - how_to: product usage question
      - other: none of the above

      Return a Classification object. Do not draft a reply.
    input:
      ticket: "${nodes.fetch_ticket.output}"
    output_schema: Classification
    tools:
      - search_knowledge_base
    policy:
      max_steps: 4
      max_tokens: 1200
      timeout_seconds: 45

  - id: route_category
    kind: router
    switch: "${nodes.classify_ticket.output.category}"
    cases:
      refund: draft_refund_reply
      bug: escalate_bug
      default: draft_general_reply

  - id: draft_refund_reply
    kind: agent
    model: claude-sonnet-5-5
    instructions: |
      Draft a concise customer reply for a refund request.
      Mention that a support lead must approve it before sending.
    input:
      ticket: "${nodes.fetch_ticket.output}"
      classification: "${nodes.classify_ticket.output}"
    output_schema: DraftReply
    tools:
      - search_knowledge_base
    policy:
      max_steps: 4
      max_tokens: 1500
      timeout_seconds: 45

  - id: approve_refund_reply
    kind: human
    input:
      draft: "${nodes.draft_refund_reply.output}"
    reviewers:
      - support-leads
    timeout_seconds: 86400
    next: send_refund_reply

  - id: send_refund_reply
    kind: task
    uses: send_reply
    input:
      ticket: "${nodes.fetch_ticket.output}"
      draft: "${nodes.approve_refund_reply.output}"
    next: finish_success

  - id: escalate_bug
    kind: task
    uses: escalate_to_support
    input:
      ticket: "${nodes.fetch_ticket.output}"
      reason: "${nodes.classify_ticket.output.rationale}"
    next: finish_escalated

  - id: draft_general_reply
    kind: agent
    model: claude-sonnet-5-5
    instructions: |
      Draft a helpful customer support reply.
      Use the knowledge base when needed.
    input:
      ticket: "${nodes.fetch_ticket.output}"
      classification: "${nodes.classify_ticket.output}"
    output_schema: DraftReply
    tools:
      - search_knowledge_base
    policy:
      max_steps: 4
      max_tokens: 1500
      timeout_seconds: 45
    next: send_general_reply

  - id: send_general_reply
    kind: task
    uses: send_reply
    input:
      ticket: "${nodes.fetch_ticket.output}"
      draft: "${nodes.draft_general_reply.output}"
    next: finish_success

  - id: finish_success
    kind: output
    value:
      ticket_id: "${nodes.fetch_ticket.output.id}"
      category: "${nodes.classify_ticket.output.category}"
      reply_sent: true
      escalated: false

  - id: finish_escalated
    kind: output
    value:
      ticket_id: "${nodes.fetch_ticket.output.id}"
      category: "${nodes.classify_ticket.output.category}"
      reply_sent: false
      escalated: true
```

## MVP IR shape

The compiler converts YAML into JSON IR. The IR should be explicit and boring.

```json
{
  "ir_version": "0.1.0",
  "name": "support_triage",
  "version": "0.1.0",
  "input_schema": "TicketInput",
  "output_schema": "TriageResult",
  "registries": {
    "tasks": "examples.support.tasks",
    "tools": "examples.support.tools",
    "schemas": "examples.support.schemas"
  },
  "nodes": [
    {
      "id": "fetch_ticket",
      "kind": "task",
      "uses": "fetch_ticket",
      "input": {
        "ticket_id": "${input.ticket_id}"
      },
      "retry": {
        "max_attempts": 3
      },
      "timeout_seconds": 10
    }
  ],
  "edges": [
    {
      "from": "fetch_ticket",
      "to": "classify_ticket"
    }
  ]
}
```

## In scope

### CLI

- `wf validate <workflow.yaml>`
- `wf compile <workflow.yaml> --out <file>`
- `wf run <workflow.ir.json> --input <input.json>`

### Node kinds

- `task`: deterministic Python function call.
- `agent`: LLM call loop with declared tools and structured output.
- `router`: switch on a simple expression and select the next node.
- `human`: local approval interrupt for CLI runs.
- `output`: terminal node that produces the workflow result.

### Validation

- Required fields per node kind.
- Unique node ids.
- All referenced nodes exist.
- Exactly one start node or explicit `start` field.
- No unreachable nodes except explicitly disabled nodes.
- No cycles in MVP workflows.
- Task/tool names exist in registries.
- Agent tools are allowlisted.
- Input/output schemas exist.
- Basic expression validation for `${input.x}` and `${nodes.<id>.output.y}` references.

### Runtime

- Load IR.
- Load Python registries.
- Execute nodes in graph order.
- Resolve expressions from workflow state.
- Validate task inputs and outputs with Pydantic models.
- Run agent nodes through one model provider adapter.
- Enforce `max_steps`, `max_tokens`, timeout, and tool allowlist.
- Pause human nodes in CLI, show input payload, accept approved JSON payload.
- Emit final output JSON.
- Write a local trace file per run.

### Observability

Each run writes `runs/<run_id>/trace.jsonl` with one event per node:

- run id
- node id
- node kind
- start/end timestamp
- status
- input reference summary
- output reference summary
- token usage for agents
- tool calls for agents
- error details when failed

## Out of scope

- Hosted service.
- Web UI.
- Visual workflow builder.
- Python SDK authoring.
- TypeScript SDK.
- Temporal adapter.
- Durable multi-day execution.
- Distributed workers.
- Advanced expression language.
- Loops.
- Parallel fan-out/fan-in.
- Nested sub-workflows.
- Multi-tenant auth.
- Secrets manager integration beyond environment variables.
- Full OpenTelemetry integration.
- Model-provider routing.
- Record/replay eval harness.

## Repository structure

```text
workflow-as-code/
  docs/
    PLAN.md
    MVP.md
  pyproject.toml
  src/
    wf/
      __init__.py
      cli.py
      compiler.py
      ir.py
      validate.py
      runtime.py
      expressions.py
      registries.py
      providers/
        __init__.py
        base.py
        anthropic.py
      backends/
        __init__.py
        langgraph.py
  examples/
    support/
      workflow.yaml
      input.json
      schemas.py
      tasks.py
      tools.py
  tests/
    test_validate.py
    test_compile.py
    test_runtime_support.py
```

## Milestones

### Milestone 1: IR and YAML validation

Deliverables:

- Pydantic models for IR.
- YAML parser.
- Validator for required fields, node ids, references, and registries.
- `wf validate` command.
- Example support workflow.

Acceptance:

- Valid example passes.
- Missing node reference fails with a clear error.
- Duplicate node id fails with a clear error.
- Unknown task/tool fails with a clear error.

### Milestone 2: Compiler

Deliverables:

- `wf compile` command.
- YAML-to-IR conversion.
- Edge derivation from `next`, router cases, and sequential default order.
- Golden JSON fixture for support workflow.

Acceptance:

- `wf compile examples/support/workflow.yaml --out build/support_triage.ir.json` writes deterministic JSON.
- Running compile twice produces the same output.

### Milestone 3: Deterministic runtime

Deliverables:

- Runtime for `task`, `router`, `human`, and `output` nodes.
- Expression resolver.
- Local state store.
- Trace JSONL writer.

Acceptance:

- Support workflow can run with agent nodes replaced by recorded fixtures or mock provider.
- Router picks the expected branch for refund, bug, and default categories.
- Human node blocks and resumes from CLI-provided approval JSON.

### Milestone 4: Agent runtime

Deliverables:

- Provider interface.
- One real provider adapter.
- Tool-use loop.
- Structured output validation.
- Policy enforcement for max steps, tokens, timeout, and tool allowlists.

Acceptance:

- `classify_ticket` returns a valid `Classification` object.
- Agent cannot call an undeclared tool.
- Invalid structured output fails with a clear validation error.

### Milestone 5: End-to-end demo

Deliverables:

- One command sequence in README or docs.
- Example input payloads.
- Example trace output.
- Demo support workflow running end to end.

Acceptance:

- Fresh checkout can validate, compile, and run the support workflow locally after installing dependencies and setting provider credentials.
- Final output matches `TriageResult` schema.
- Trace file shows every executed node.

## MVP acceptance criteria

The MVP is done when these commands work:

```bash
wf validate examples/support/workflow.yaml
wf compile examples/support/workflow.yaml --out build/support_triage.ir.json
wf run build/support_triage.ir.json --input examples/support/input.json
```

And the run proves:

- deterministic task execution
- explicit agent execution
- tool allowlist enforcement
- router branch selection
- human approval interrupt
- structured final output
- local trace generation

## Main risks

| Risk | Mitigation |
|---|---|
| YAML grows into a programming language | Keep YAML declarative; push business logic into registered tasks/tools |
| Agent behavior is vague | Require instructions, output schema, tools, and policy for every agent |
| IR becomes LangGraph-shaped | Keep IR node kinds generic; isolate LangGraph in adapter/runtime layer |
| Human approval blocks automation | Use CLI prompt for MVP; persist pending state locally |
| Provider APIs change | Keep one small provider interface and pin dependencies |
| Non-deterministic tests | Use fake/recorded provider for tests; reserve real provider for smoke demo |

## Post-MVP

- Python SDK authoring that compiles to the same IR.
- Visual designer that edits YAML or IR.
- Durable runtime with Temporal.
- Parallel branches and joins.
- Sub-workflows.
- Eval harness with record/replay.
- OpenTelemetry traces.
- Hosted control plane.
