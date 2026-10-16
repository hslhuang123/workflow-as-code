# Workflow-as-Code Platform: Plan

## 1. Core idea

Users write workflows in a typed code SDK. The platform compiles that code into a backend-neutral graph (an IR), validates it, and executes it through a pluggable backend such as LangGraph. Each node declares its kind explicitly: deterministic task, LLM agent, router, human step, or sub-workflow. The platform never silently decides whether a step uses an LLM.

```
 user code (Python SDK)
        │  import / AST
        ▼
 ┌──────────────┐   validate   ┌──────────────┐   adapter   ┌────────────────────┐
 │  Compiler    │ ───────────▶ │  Workflow IR │ ──────────▶ │ LangGraph (default)│
 │  (typed DSL) │              │  (JSON graph)│             │ Temporal / others  │
 └──────────────┘              └──────────────┘             └────────────────────┘
```

## 2. Authoring model

Python is the likely first choice because the LLM tooling is strongest there. Illustrative sketch:

```python
from wf import workflow, task, agent, branch

@task                       # deterministic: plain code, no LLM
def fetch_ticket(ticket_id: str) -> Ticket: ...

@agent(model="claude-sonnet-5-5", tools=[search_kb, get_customer])   # reasoning
def classify(ticket: Ticket) -> Category: ...

@task
def send_reply(draft: Draft) -> None: ...

with workflow("triage", input=TicketInput) as wf:
    t   = fetch_ticket(wf.input.ticket_id)
    cat = classify(t)
    with branch(cat) as b:
        b.when("refund", lambda: refund_flow(t))
        b.otherwise(lambda: auto_reply(t))
```

Principles:
- **Explicit node kinds.** `@task` is deterministic, `@agent` is LLM-driven, and `branch` is control flow. Reviewers can see at a glance what is probabilistic.
- **Typed inputs and outputs.** These become the state schema and the validation contract between nodes.
- **Tools are declared, not discovered.** Each agent gets an allowlist of tools, which bounds cost and risk.
- **Policies are per node.** Retries, timeouts, token budgets, and human-approval gates are attached to nodes, not hidden in the runtime.

## 3. Components

| Component | Responsibility | Notes |
|---|---|---|
| **SDK** | Decorators, context managers, typed signatures | Thin; no execution logic |
| **Compiler** | Parse user code into IR, type-check, detect cycles and dead nodes | Use AST inspection, not `exec` |
| **IR** | Versioned JSON graph: nodes, edges, state schema, policies | The stable contract; everything else targets it |
| **Backend adapters** | IR → LangGraph; later IR → Temporal or a native engine | Avoids lock-in to LangGraph |
| **Node runtimes** | `task` runs functions. `agent` runs an LLM tool-use loop via the model gateway | Start with LangChain or the Anthropic SDK for the agent loop |
| **Model gateway** | Provider abstraction, rate limiting, token accounting, caching | Route by model ID in node config |
| **Tool registry** | Typed tools, MCP-compatible | Lets agents use external tools safely |
| **State and checkpoints** | Persist per-step state for resume, retries, and human-in-the-loop | LangGraph checkpointers cover the MVP |
| **Observability** | Traces per node, token and cost per run, replay | OpenTelemetry-compatible |
| **Eval harness** | Record/replay LLM calls, golden tests, output assertions | Essential, because LLM nodes are non-deterministic |
| **CLI and API** | `wf validate`, `wf run`, `wf export`, `wf eval` | Also the surface CI uses |

## 4. Key decisions

1. **Interpret vs. generate.** Interpreting the IR at runtime is more flexible and easier to version. Generating LangGraph source is more transparent and easier to debug, but harder to keep in sync. **Recommendation:** interpret the IR, and offer `wf export` to emit readable LangGraph code for teams that want to own it.
2. **Who selects the executor?** Auto-picking the executor from the code is tempting but risky. **Recommendation:** the author declares the kind. An optional LLM-assisted linter can suggest "this looks like reasoning, consider `@agent`", and the author confirms.
3. **Durability.** For long-running or human-gated workflows, plain LangGraph checkpoints may not be enough. Temporal is the usual answer for durable execution across days and retries at scale.
4. **Target user.** Developers writing code, or non-developers using a visual view generated from the IR? The IR is the same either way, but UI scope differs a lot.
5. **Hosting.** Self-hosted library and CLI first, then a hosted service? Multi-tenant concerns come later.

## 5. Phased roadmap

**Phase 0: Spike (1–2 weeks).** Hand-write one workflow with two deterministic tasks and one agent node in LangGraph. Confirm that state passing, tool calls, and a human-approval interrupt work well.

**Phase 1: IR and compiler (3–4 weeks).** Build the SDK decorators, the versioned IR schema, validation, and a `wf validate` CLI. Add a golden-file test suite: user code → IR snapshot.

**Phase 2: LangGraph adapter and runtime (3–4 weeks).** Compile IR to LangGraph. Add the model gateway, tool registry, per-node retries and timeouts, checkpoints, and `wf run`. Trace every node.

**Phase 3: Evals and safety (3 weeks).** Record/replay for LLM calls, assertions, token budgets, tool allowlists enforced at runtime, and a sandbox for code-executing tools.

**Phase 4: Developer experience (ongoing).** Generated graph visualization from the IR, `wf export`, a second backend (e.g., Temporal) to prove the abstraction holds, and an optional web UI.

## 6. Risks

- **Non-determinism in LLM nodes** makes testing and debugging hard. Mitigate with record/replay, structured outputs, and strict schemas.
- **Cost runaway** in agent loops. Mitigate with per-node token and step limits.
- **Leaky abstraction.** If the IR bends to fit LangGraph, a second backend will be painful. Keep the IR minimal and backend-neutral, and test it against two backends early.
- **Tool security.** Agents that write data or run code need allowlists, approval gates, and audit logs.
- **Framework churn.** LangChain and LangGraph change quickly. Pin versions and keep the adapter layer thin.

## 7. Open questions

- Language: Python, TypeScript, or both?
- Primary user: a developer writing code, or a non-developer using a visual tool?
- Model provider: a preferred provider, or provider-neutral from day one?
- Is durability across long-running or human-gated workflows a near-term requirement? If so, evaluate Temporal alongside LangGraph in Phase 0.
