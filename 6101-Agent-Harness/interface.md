# Agent Harnesses - Gate & Infrastructure Interface

**Audit correction, 20 October 2026:** This describes the existing contract, not verified end-to-end readiness. The current gate assumes dict tool calls whereas AgentDojo uses FunctionCall objects; task propagation, repeated execution, mixed batches and audit integration require repair. The current factory is a single pass, not a complete multi-turn loop. See [the decision register](../R3/PROJECT_DECISION_REGISTER.md). The policy and reviewer implementations now reside in policy.py and reviewer.py; core interfaces remain in types.py.

## Overview

This module implements a safety gate for LLM agents using the AgentDojo framework.
The gate intercepts tool calls, applies a policy to decide approval/denial/escalation,
and optionally consults a reviewer for escalated calls.

## Repository Structure
```plain
6101-agent-harness
├── src/
│ ├── types.py # Core type definitions
│ ├── gate.py # GateElement - tool approval gate
│ ├── budget.py # BudgetResetElement - per-task budget reset
│ ├── policy.py # Full-approve/full-escalate implementations; interface in types.Policy
│ ├── reviewer.py # LLM reviewer implementation; interface in types.Reviewer
│ ├── risk_based_policy.py # RiskBasedPolicy - YAML-driven policy
│ ├── tool_risk.py # YAML loader for tool risk metadata
│ ├── tool_risk_metadata.yaml # Tool risk configuration
│ └── pipeline.py # build_pipeline factory
├── tests/ # Unit tests (23 tests)
├── configs/ # Experiment configs (empty)
└── conftest.py # Pytest fixtures
```
## Components

### 1. `types.py`

Core type definitions:

| Type | Description |
|------|-------------|
| `Decision` | Enum: `AUTO_APPROVE`, `AUTO_DENY`, `ESCALATE` |
| `GateInput` | Input to policy/reviewer: tool name, args, metadata, trajectory, user task, remaining budget |
| `GateOutput` | Output from policy: decision, risk score, rationale |
| `GateResult` | Result of processing a tool call through the gate |
| `Policy` | Interface: `decide(gate_input) -> GateOutput` |
| `Reviewer` | Interface: `approve(gate_input) -> bool`, `deny(gate_input) -> bool` |

### 2. `gate.py`

`GateElement` - wraps `ToolsExecutor` and intercepts tool calls:

- For each `tool_call` in the message:
  - Calls `policy.decide(GateInput(...))`
  - If `AUTO_APPROVE`: pass through
  - If `AUTO_DENY`: construct `ChatToolResultMessage` with error "Blocked by gate"
  - If `ESCALATE`:
    - If `k_remaining > 0`: consult reviewer, decrement budget
    - If `k_remaining == 0`: auto-deny (degrade to AUTO_DENY)
- Records `GateResult` for each tool call in `self.gate_results`

**Constructor:**

```python
    GateElement(policy: Policy, reviewer: Reviewer, k: int, tool_risk_metadata: Dict[str, Dict[str, Any]])
```

**Key attributes:**

- `k_remaining`: current escalation budget
- `gate_results`: list of `GateResult` for debugging/analysis

### 3. `budget.py`

`BudgetResetElement` - resets the escalation budget to `initial_k` at the start of each task.

**Constructor:**
```python
BudgetResetElement(initial_k: int)
```
### 4. `tool_risk.py`

Loads tool risk metadata from YAML:
```python
load_tool_risk_metadata(path: str) -> Dict[str, Dict[str, Any]]
risk_for(metadata: Dict, tool_name: str) -> Dict[str, Any]
```

### 5. `risk_based_policy.py`

`RiskBasedPolicy` - decides based on tool risk metadata:

- `low` risk → `AUTO_APPROVE`
- `medium`/`high` risk → `ESCALATE`
- `default_decision` in YAML overrides risk-based logic

**Constructor:**
```python
RiskBasedPolicy(tool_risk_metadata: Dict[str, Dict[str, Any]])
```

### 6. `pipeline.py`

`build_pipeline` factory:
```python
build_pipeline(
model: str,
policy: Policy,
k: int,
reviewer: Reviewer,
tool_risk_metadata: Dict[str, Dict[str, Any]],
system_prompt: str = "",
client: Optional[OpenAI] = None,
) -> AgentPipeline
```
Assembles the full pipeline:

SystemMessage → InitQuery → BudgetReset → LocalLLM → Gate → ToolsExecutor

## Tool Risk Metadata YAML

Schema v2 uses suites.<suite_name>.tools.<tool_name> with common defaults. All 74 registrations have explicit action families, scope-check tags, parameter names, source paths and source hashes. These are metadata, not a completed scope-aware policy. Newly added tools conservatively escalate; banking reference decisions remain unchanged.

```yaml
schema_version: 2
benchmark_version: v1.2.2
defaults:
  risk: medium
  category: execute
  default_decision: ESCALATE
suites:
  workspace:
    tools:
      send_email:
        risk: high
        category: write
        default_decision: ESCALATE
        action_family: communication
```

Use load_tool_risk_metadata(path, suite_name="workspace") for a dict-compatible selected view. Without selection, unambiguous names remain compatible while overlapping names conservatively fall back. risk_for(metadata, tool_name, suite_name=None) cannot borrow a definition from a different suite. Legacy flat tools YAML still loads.

GateInput, GateResult, GateElement, RiskBasedPolicy, make_policy and build_pipeline accept optional suite_name. The new planner defaults to all suites; see README for command flags. Separate executor compatibility blockers remain unresolved by this metadata/planner change.

## Usage
```python
from src.pipeline import build_pipeline
from src.risk_based_policy import RiskBasedPolicy
from src.tool_risk import load_tool_risk_metadata
Load tool risk metadata
md = load_tool_risk_metadata("src/tool_risk_metadata.yaml")
Create policy
policy = RiskBasedPolicy(md)
Create pipeline
pipeline = build_pipeline(
model="qwen3:14b",
policy=policy,
k=5,
reviewer=my_reviewer,
tool_risk_metadata=md,
system_prompt="You are a banking assistant.",
)
```
## Testing
```bash
pytest tests/ -v
Expected: 18 tests passing.
```
## Changelog

### v0.2.0 (Oct 13, 2026)

- Initial gate implementation
- RiskBasedPolicy with YAML metadata
- Pipeline factory with BudgetReset
- 23 unit tests passing