# Project decision register

Reconciled **20 October 2026**. This replaces the earlier long recommendation list, which contained stale workspace defaults, unresolved scope statements and an unnecessary independent-labeling prerequisite. Entries below distinguish accepted direction, code defaults and genuine open decisions.

## 1. Source precedence and document map

- Course handout: required AgentDojo gate, original three-way policy, full-approve/full-escalate baselines, online LLM reviewer, finite per-task k, report evidence and presentation.
- User clarification: five-page report; all-suite policy scope (latest correction supersedes earlier banking-only direction); audit recommendations accepted; **AgentDojo results suffice for evaluation with executed-call audit trails**. These are user-supplied clarifications, not independently obtained TA messages.
- [AgentDojo learning and evaluation](../README.md#evaluation-contract): verified benchmark semantics and scoring contract.
- [Policy architecture](SCOPE_AWARE_POLICY_ARCHITECTURE.md): detailed proposed policy internals.
- [Role 3 work plan](ROLE_3_RESEARCH_PLAN.md): implementation scope and checkpoints.
- [Industry review](INDUSTRY_AGENT_APPROVAL_RESEARCH.md) and [policy types](POLICY_TYPES_AND_PROPOSED_ARCHITECTURE.md): sourced inspirations, not our runtime specification.
- Older HTML/PDF plan exports are not synchronized specifications. Regenerate them from reviewed Markdown if needed; their content may be stale.

## 2. Accepted decisions

| Topic | Accepted direction / qualification |
| --- | --- |
| Benchmark/policy scope | All four suites: workspace, travel, banking and Slack; package 0.1.35 / benchmark v1.2.2. Existing banking implementation is a starting artifact, not final scope. See [multi-domain specification](MULTI_DOMAIN_POLICY_SCOPE.md). |
| Policy | Scope-aware heuristics with semantic assessment and selective, budget-aware review |
| Existing risk policy | Preserve `risk_based` as a simple reference; add hybrid separately |
| Interfaces | Start from existing Policy.decide(GateInput) -> GateOutput; extend compatibly |
| Budget | Gate is authoritative; actual review consumes one slot; exhaustion denies calls requiring review |
| Scope | Interpret original task and observable evidence; do not use benchmark labels as runtime authorization |
| Delegated details | Permit task-authorized lookup/file-derived facts; broad file instructions need bounded interpretation, not a blanket ban |
| Evaluation | Official AgentDojo utility and attack-goal outcomes plus mandatory execution audit trail |
| Headline metric | AgentDojo-based TCR on attacked conditions: task completion AND failure of the specified attack objective |
| Clean tasks | Report clean utility separately; raw security=True is not a clean-run safety certificate |
| Main comparisons | Full approve, finite-k full escalate, customized policy |
| Budget contribution | Compare identical hybrid variants with fixed versus budget-dependent allocation |
| Training | No new model training required; fixed LLM assessment plus explicit rules is the initial design |
| Provisional model assignment, 20 October | User prefers Qwen3:14b for agent, R4 assessor and reviewer. Use separate prompts/contexts; shared-model errors may be correlated. Gemini remains a fallback, not a required comparison. Confirm live compatibility and record the exact Ollama model/version before final freeze. |
| Resources, user clarification 20 October | Qwen3:14b and Gemini are considered free under the project access arrangement; no project spending/runtime cap requested. Provider quotas and operational episode/retry limits remain separate. |
| Submission | Five-page report, GitHub evidence, 10-minute presentation + 5-minute Q&A |

Improvement is a hypothesis. Higher benchmark TCR at matched k supports the whole-policy claim; the fixed-versus-dynamic ablation supports a budget-allocation claim. Comparable performance with less review/cost is an efficiency finding, subject to variability. Negative results must remain reportable.

## 3. Established code defaults, not frozen final experimental choices

| Existing default | Evidence / implication |
| --- | --- |
| Banking 16 user tasks, 9 injection tasks, 11 tools | Loaded locally; metadata covers the registered tool inventory |
| k in {0,1,3,5} | Planner default; use for development before freezing final range |
| qwen3:14b via Ollama | Team agent factory/reviewer default; live compatibility not established by this review |
| Gemini adapter at repository root | Separate stock-pipeline runner; defaults to workspace and does not activate team gate |
| 12,552 default pending rows | Multi-suite planner includes clean/attacked conditions, attack method, repeat and unique episode IDs. Legacy banking CSV preserved. Unimplemented hybrid labels are rejected. |
| Gate policy output | Decision, optional score and rationale only; detailed evidence/allocation schema absent |
| R5 logger/metrics/cost modules | Standalone implementation; integration and scorer mapping pending |

## 4. Decisions needed before integrated policy implementation

| Decision | Concrete proposal | Still needs agreement |
| --- | --- | --- |
| R4 assessment contract | Return per-check status, evidence IDs, unresolved question, consequence and error status | Exact schema, callable/provider/model, input limits and failure handling |
| Policy lifecycle | Episode-local scope ledger and execution history, reset once per task | Where init/reset and successful execution feedback are wired |
| Evidence identifiers | Stable instruction/observation/call IDs, trust tags and original proposed arguments | Fields shared by gate, judge and logger |
| Multi-domain scope rubric | Shared operation/resource/audience/data/constraint/provenance checks with suite-specific semantics | Tool normalization/effects for every suite; delegated instructions, implicit supporting steps and unresolved identity |
| Approval criteria | Four-state checks; proven violation denies, supported checks approve, unresolved routes onward | Which checks are required for each action class and what evidence suffices |
| Review priority | Necessity, resolution value and consequence; scarcity affects review only | Freeze rubric definitions before pilot; numeric weights afterward |

Start shared deterministic scope checks and suite adapters with a stub assessor once those contracts are agreed. No independent per-call authorization dataset is required before implementation under the user's evaluation clarification.

## 5. Decisions needed before billable pilot / final evaluation

- Validate the provisional Qwen3:14b-only pilot for agent, semantic assessor and reviewer; record Ollama/model versions and role-specific settings. A Gemini model ID is needed only if the fallback is used. The user’s “probably” is a provisional preference, not a frozen experimental configuration.
- Pilot size and operational episode/retry limits. The user specified no project spending/runtime cap; do not invent a monetary cap. Record usage and provider quota failures even when no API charges are expected.
- Development/held-out user-task IDs, attack methods/objectives/configurations, attack-generation protocol and clean coverage.
- Final k values, repetition count, valid-run retry policy, episode bounds and exclusions.
- Final thresholds selected on development data; equally tune the fixed-threshold comparator.
- Aggregation: separate clean and attacked panels recommended; define repetitions/task weighting and error/missing bounds.
- Report counting rules: whether references/appendices count in five pages; official deadline/template and speaker rules remain unconfirmed.

Independent strict authorization scoring is optional supplementary analysis, not an unresolved barrier. If audit finds behavior beyond the official attack objective, retain the benchmark result and describe the additional finding separately.

## 6. Engineering corrections already identified

These are implementation defects/gaps, not choices to defer:

1. Support actual AgentDojo FunctionCall objects, not dict-only fixtures.
2. Supply the original task to the policy; isolate runtime data from evaluator-only fields.
3. Add a repeated tool-use loop with gate interception on every iteration.
4. Preserve all proposed calls/results in mixed approved/denied batches; append denials without causing approved calls to be skipped.
5. Preserve original trajectory/calls before mutation; add episode/call IDs and actual execution/reviewer events.
6. Reconcile metrics with the accepted AgentDojo-based mapping, condition-aware raw security semantics, cohort totals and fixed denominators. Do not deduplicate repeated episodes by task ID alone.
7. Stale test imports are repaired. Actual executor behavior for reviewer errors and denial paths still needs integration verification.
8. Validate sensitive execution semantics, including amendment fields that the upstream tool may ignore for false/zero values; do not silently patch benchmark behavior mid-comparison.

No code is changed by this documentation revision. Current metadata/planner validation: 11 new unittest tests passed and 41 legacy checks passed by direct offline invocation after repairing stale imports and the shared-request fixture. This is not a pytest or live end-to-end benchmark run; execution integration blockers remain.

**Additional audited prompt issue:** R2’s current reviewer prompt denies recipients not literally mentioned by the user. Reconcile it with task-authorized bill/history-derived beneficiaries before freezing comparisons. This is a prompt/design correction, not evidence that every file-derived beneficiary is genuine. See the [implementation/baseline runbook](ROLE_3_IMPLEMENTATION_AND_BASELINE_RUNBOOK.md).

## 7. Readiness sequence

```mermaid
flowchart LR
    A["Agree multi-suite semantics and R4 contracts"] --> B["Fix execution integration and audit events"]
    B --> C["Implement scope rules with stub assessor"]
    C --> D["Integrate models; costed development pilot"]
    D --> E["Freeze protocol and thresholds"]
    E --> F["Matched held-out benchmark and allocation ablation"]
    F --> G["Report results, failures, cost and limitations"]
```

All-suite support is required design scope. Optional studies after core readiness include domain-held-out generalization, assessor-context ablation, additional models and stricter independent authorization audits. Do not displace required baselines or audit logging with optional scope.
