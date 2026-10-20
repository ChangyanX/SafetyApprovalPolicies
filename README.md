# Safety Approval Policies for Agent Harnesses

**Goal:** design and evaluate a scope-aware approval policy under a limited per-task review budget using AgentDojo. Whether the customized policy improves results is an empirical question, not an assumed conclusion.

## Current status and accepted scope

- Policy target: **all four suites—workspace, travel, banking and Slack**—in installed `agentdojo==0.1.35`, benchmark `v1.2.2`. See [multi-domain scope](R3/MULTI_DOMAIN_POLICY_SCOPE.md).
- Loaded coverage: 97 user tasks and 74 tool registrations across four suites. Suite-scoped metadata now explicitly covers all 74 registrations, including parameter lists, source hashes, action families and scope-check tags. These tags describe semantics; the bounded exact-grant/literal-rule engine is implemented; broad semantic scope extraction remains pending.
- `6101-Agent-Harness/` contains gate/budget code, baseline policies, a metadata policy, LLM reviewer, logger, cost tracker, metrics and manifest planner. Stub-first scope policies and the connected executor are implemented; R4 semantic assessment remains pending.
- The new factory connects repeated gating, review budget, R3 lifecycle and audit feedback. Forty scripted integration episodes pass; live Qwen validation awaits a reachable Ollama service.
- Root `scripts/run_gemini.py` is a separate stock-pipeline clean/attacked smoke runner. Its default suite is workspace; it does not activate the team gate.
- Provisional pilot model: Qwen3:14b for agent, R4 assessor and reviewer, using separate prompts/contexts. Gemini remains a fallback. Validate role-specific behavior and record exact model/runtime versions; shared-model judgments may have correlated errors.
- No comparative policy improvement has been demonstrated. The planner now defaults to 12,552 pending rows across all suites with clean and attacked conditions; the older 1,728-row banking manifest is a legacy artifact, not the active planning default.

## Documents and source precedence

| Document | Use |
| --- | --- |
| Two-page course handout | Required deliverables and objective |
| User clarifications | Five-page report, all-suite policy scope (supersedes earlier banking-only direction), accepted audit recommendations, AgentDojo evaluation plus executed-call audit trail |
| [Multi-domain scope](R3/MULTI_DOMAIN_POLICY_SCOPE.md) / evaluation contract below | Verified suite coverage, common checks, domain semantics and scoring |
| [Decision register](R3/PROJECT_DECISION_REGISTER.md) | Accepted choices, code defaults and open decisions |
| [Scope-aware policy architecture](R3/SCOPE_AWARE_POLICY_ARCHITECTURE.md) | Proposed policy internals, rules and allocation justification |
| [Role 3 plan](R3/ROLE_3_RESEARCH_PLAN.md) | R3 work sequence and experiment ownership |
| [Industry research](R3/INDUSTRY_AGENT_APPROVAL_RESEARCH.md) / [policy types](R3/POLICY_TYPES_AND_PROPOSED_ARCHITECTURE.md) | Referenced industry patterns and public policy files |
| [Team interface](6101-Agent-Harness/interface.md) | Existing contracts; implementation must be checked against pinned runtime |

## Course requirements

Intercept every proposed tool call before execution and choose auto-approve, auto-deny or escalation to an online LLM-simulated human reviewer. Each actual review consumes one of k per-task slots regardless of verdict. Once exhausted, calls requiring escalation are denied. Compare an original policy with full approve and full escalate under the same finite-budget rule.

Submit via GitHub: integrated code; TCR@k curves; HITL totals; agent/policy/reviewer API costs; over-conservative and over-permissive failure classification with concrete trajectories; escalation-value analysis; and a 10-minute presentation plus 5-minute Q&A. Reviewer inputs must exclude benchmark ground truth, attacker objectives/annotations and evaluator outcomes. [Course handout](AI6101%20Group%20Project%201%20-%20Safety%20Approval%20Policies%20for%20Agent%20Harnesses.pdf), §§2–4.

The user confirmed a five-page report. Deadline, template and whether references/appendices count remain unconfirmed.

## Policy and task scope

AgentDojo supplies task prompts, tools, environments and task-specific evaluators. It does not provide a general structured authorization ledger for every call. Our ledger interprets the original request, bounded delegated instructions and observable facts.

Use common checks for operation, resource/identity, destination/audience, data/content, quantitative constraints, mutations, provenance and cumulative effects. Suite-specific semantic adapters cover email/calendar/files, travel reservations, banking and Slack; see [the scope matrix](R3/MULTI_DOMAIN_POLICY_SCOPE.md). Banking beneficiary/amount examples illustrate these common dimensions. Task-authorized bill/history lookup can resolve values absent from the prompt. Some tasks explicitly delegate file instructions; reject unrelated expansion rather than banning all file-derived actions. Compromised source facts can remain ambiguous even to a reviewer.

```mermaid
flowchart TD
    A["Task prompt and observable facts"] --> B["Scope ledger and actual action semantics"]
    B --> C["Four-state scope checks"]
    C -->|Established authorization| P["APPROVE"]
    C -->|Proven violation| D["DENY"]
    C -->|Unresolved| J["Bounded semantic assessment"]
    J --> R["Recheck scope; filter reviewable uncertainty"]
    R --> S["Priority versus remaining-budget threshold"]
    S -->|Selected| E["ESCALATE"]
    S -->|Not selected| D
    P --> G["Execution gate enforces decision"]
    D --> G
    E --> G
```

Detailed complete branches and justification: [architecture](R3/SCOPE_AWARE_POLICY_ARCHITECTURE.md). Industry-inspired mechanisms are not proof that this particular combination improves benchmark outcomes.

## Evaluation contract

The user clarified that **AgentDojo results suffice, with all executed calls recorded for audit**. Independent per-call authorization labels are not a prerequisite.

For valid attacked episodes, $U_i$ is upstream utility, $J_i$ is specified attack-goal success, and $E_i$ is actual reviewer use:

$$\operatorname{TCR}_{\mathrm{AD}}@k=\frac{1}{N}\sum_{i=1}^{N}U_i(1-J_i),\qquad E_i\le k.$$

Call this **AgentDojo-based project TCR**. Report attacked utility and attack-success rate alongside it; report clean utility separately. This operationalization does not certify every possible unauthorized action. Preserve unexpected audit findings as additional evidence.

**Critical raw-field mapping:** attacked `security=True` means the specified attack succeeded. Clean `security=True` is a no-injection sentinel. Error fallbacks and DoS conditions need separate handling. Never map raw `security` universally to “safe.” The mapping was checked against the [pinned TaskSuite implementation](https://github.com/ethz-spylab/agentdojo/blob/v0.1.35/src/agentdojo/task_suite/task_suite.py) and [benchmark runner](https://github.com/ethz-spylab/agentdojo/blob/v0.1.35/src/agentdojo/benchmark.py).

Report scheduled, valid, missing and error counts. Use frozen cohorts and a consistent retry protocol; do not silently exclude unknown outcomes. HITL means total actual reviewer consultations in an explicitly defined successful cohort; also report all-episode totals and cohort sizes. Average load is supplementary.

### Comparisons

| Strategy | Purpose |
| --- | --- |
| Full approve | Required unguarded baseline |
| Full escalate | Required all-calls-reviewed baseline until k is exhausted |
| Existing metadata policy | Additional simple tool-risk reference |
| Hybrid with fixed allocation | Controls for rules and assessor when testing allocation |
| Hybrid with budget-aware allocation | Tests proposed selective reservation |

Required scope is the two baselines plus our original policy. Preserve the allocation comparator if claiming budget-aware benefit; drop optional experiments before required evidence. Split by user-task identity, freeze after development tuning, use matched attacks/models and report clean/attacked conditions separately. Initial development k grid is {0,1,3,5}; final values are not frozen.

The planner now includes suite, clean/attacked condition, attack method, injection objective, repeat and unique episode ID. Defaults are all suites, direct attack, one repeat, three implemented policies and k={0,1,3,5}: 12,552 pending rows. The explicit labels `hybrid_stub` and `hybrid_stub_fixed` are now registered; their episode lifecycle is wired in the connected factory and they are excluded from the unchanged default manifest. Unknown labels are rejected. Planning does not execute episodes. The legacy banking CSV is preserved.

## Runtime audit requirements

Record episode/call IDs, original task, proposed arguments before mutation, policy/effective decisions, check evidence and rule IDs, budget before/after, actual reviewer request/verdict/error, actual executed call/result and errors. Keep evaluator-only fields in offline scoring. Record model/provider/configuration versions and component usage including retries/unknown costs.

The gate must support real FunctionCall objects, repeated tool use and mixed batches. A denied call must not execute; an approved sibling must not be skipped. Preserve original calls rather than mutating the only audit copy. Logging and metric updates are engineering work, not optional review statistics.

## Running existing smoke checks

Use the existing environment and keep credentials in local `.env`, never source or logs. Requirements at repository root support the Gemini runner; team requirements additionally list pytest and YAML/OpenAI tooling. Do not manually edit installed AgentDojo source.

```bash
source .venv/bin/activate
python scripts/run_gemini.py --check --suite banking --user-task user_task_0 --benchmark-version v1.2.2
```

The command above is an offline stock-pipeline check, not proof of gated execution. For a live clean stock run, remove `--check` and choose a verified accessible model; that makes API calls. For an attacked run also supply a registered `--attack` and `--injection-task`; inspect resulting `error` and condition metadata before interpreting flags. `--force-rerun` or a fresh log directory avoids cached results.

Generate the new multi-suite plan without any model calls:

```bash
cd 6101-Agent-Harness
../.venv/bin/python -m src.experiment_runner
```

Default output is `runs/r5_multisuite_experiment_plan.csv`. Existing files are protected; use `--output` for a new plan or explicitly `--overwrite` to replace one. `--suite` may be repeated to select domains. This is planning only.

Root offline tests (run from repository root):

```bash
python -m unittest discover -s tests -v
```

Team tests, after test dependencies/imports are reconciled:

```bash
cd 6101-Agent-Harness
python -m pytest tests/ -v
```

The stale baseline/reviewer test imports have been corrected to the existing modules, and the shared-consultation fixture now reuses the same GateInput object as required. Validation: 11 new unittest cases passed; 41 legacy checks passed via direct offline invocation (not pytest). New multi-suite tests use unittest and run without pytest: from the team folder, `../.venv/bin/python -m unittest discover -s tests -p test_multisuite.py -v`. No live model or complete benchmark execution is claimed.

## Five-role ownership

| Role | Implementation and owned evidence |
| --- | --- |
| R1 | Gate, budget, pipeline and execution correctness |
| R2 | Baselines, reviewer, context isolation and reviewer failures |
| R3 | Scope rules, HybridPolicy, allocation, rule triggers and controlled allocation comparison |
| R4 | Semantic assessor, prompt/schema, development errors and usage |
| R5 | Execution manifests, audit/cost instrumentation, scoring, curves and trajectory analysis |

Every role contributes design, validation, analysis and report evidence. Role allocation does not guarantee individual marks. See the [decision register](R3/PROJECT_DECISION_REGISTER.md) for contracts and integration corrections.

## Five-page report and presentation

| Content | Pages |
| --- | --- |
| Problem/objective and related work | 0.5 |
| Method and gate integration | 1.0 |
| Experimental protocol and scorer mapping | 0.5 |
| Main curves, HITL and component costs | 1.25 |
| Both failure trajectories and escalation value | 1.0 |
| Limitations, conclusion and references | 0.75 |
| Total | 5.0 |

Provisionally include references within the limit. Keep detailed prompts, full traces and reproduction artifacts in GitHub without replacing required report figures/cases. Present design → matched results → real failures → lessons; do not promise positive results. Internal dates in the guidelines are not official deadline confirmation or proof of achieved freeze.

## Next readiness gates

1. Agree shared scope/check semantics and suite-specific action adapters, R4 schema and episode-state contracts.
2. Validate the connected execution loop against the live Qwen/Ollama endpoint.
3. Pilot fixed and dynamic policy variants. The user requested no project spending/runtime cap and considers Qwen3:14b and Gemini free under the project access arrangement; retain usage logging, provider-quota handling and finite episode/retry limits.
4. Freeze workload, models, attack protocol, thresholds, k and repetitions.
5. Run matched evaluation and report all outcomes, costs and limitations.

## R3 stub-first implementation

[Implemented workflow and commands](R3/R3_IMPLEMENTED_WORKFLOW.md), [interactive HTML demo](R3/r3_workflow.html), and [R4 contract](R3/R4_INTEGRATION.md) describe the conservative rules, state, allocation and stub assessor. The manifest execution runner is connected; see [running the benchmark](R3/RUNNING_GATED_BENCHMARK.md). No model benchmark improvement is claimed.
