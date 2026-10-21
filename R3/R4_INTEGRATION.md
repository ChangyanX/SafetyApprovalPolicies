# R3/R4 integration: wire contract r3-r4/0.1

The live combined policy is implemented as `hybrid_llm`; `hybrid_llm_fixed` uses identical semantic processing with a fixed allocation threshold. Behavior version is `r3-r4-review-selection-v1`. Read [the authoritative combined-policy specification](../docs/R3_R4_POLICY.md) and [banking run guide](../docs/BANKING_EVALUATION_GUIDE.md). Earlier advisory-only integration is retained in explicit stub ablations and historical results.

## Callable and runtime wiring

`LocalR3Assessor.assess(request: AssessmentRequest) -> AssessmentResponse` uses local `qwen3:14b` in a separate context from the agent and reviewer. `run_experiments` injects it into both live labels, persists trace/API usage, and records the behavior version. The factory selects `assessment_mode='review_selection'` for live labels and `assessment_mode='advisory'` for stub labels.

For offline transport tests, inject an assessor through `make_policy('hybrid_llm', policy_options={'assessor': fake_assessor})`. Direct construction defaults to the conservative advisory ablation; explicitly select `ScopeAwarePolicy(assessor=assessor, assessment_mode='review_selection')` to test the combined behavior. Do not describe a scripted assessor as a live model result.

## Request

The [Python contract](../6101-Agent-Harness/src/r3_contracts.py) and generated [request schema](contracts/request.schema.json) are authoritative. Requests contain schema/version identity, episode/call IDs, proposal hash, suite/tool/effective arguments, verified tool metadata/description/schema, original task, existing checks, bounded evidence and the focused question. They exclude evaluator labels, attacker objectives and hidden environment state. Evidence provenance does not authenticate content; tool observations can contain prompt injection.

## Response and validation

Echo schema version, episode ID, call ID and proposal hash exactly. Use status `ok`, `unavailable` or `error`. Successful responses have `error=null`; failures have no checks and a nonempty error. Return only unresolved requested check IDs, once each, with status `SATISFIED`, `VIOLATED`, `UNRESOLVED` or `NOT_APPLICABLE`, a nonempty reason up to 1,200 characters, and unique existing evidence citations. A valid empty checks list is permitted. Do not return execution decisions, confidence probabilities, chain-of-thought or additional fields.

R3 validates the entire response atomically before applying findings. Stale identities, repeated/nonrequested checks, missing/invented/duplicate citations, invalid statuses and contradictory error payloads leave the original fallback unchanged.

## Decision-effective use

Eligible findings require verified semantics, valid original scope, complete episode evidence in the request, citation of original instruction `u0001`, and a `SATISFIED` or `VIOLATED` status on an unresolved semantic check. `semantics`, `effect_limit` and `rent_binding` are protected from model override. Ineligible findings are audited as ignored.

An eligible semantic `VIOLATED` finding denies the call without a reviewer consultation. Supported `scope` plus `operation` can raise review relevance to $\max(n_t,0.75)$, but never establish execution permission. Deterministic check states remain unchanged. Every semantically supported call that lacks a complete deterministic grant still needs selection under the allocation threshold and independent reviewer approval. Budget zero still denies. `NOT_APPLICABLE` cannot remove a required check.

Citation validity is not proof that the model's interpretation is correct. False conflicts can be over-conservative; false relevance can waste reviewer slots. Measure both using fresh matched runs. General scope extraction that creates validated grants remains separate work.

## Audit and acceptance

`policy_audit.semantic_influence` records mode/version, complete-evidence flag, accepted/ignored check IDs, semantic conflicts and supported relevance. Allocation records original and effective necessity. `semantic_decisions.csv` makes these changes inspectable beside actual review and invocation outcomes. Policy version and source/prompt hashes prevent resuming an advisory run as a combined-policy run.

Acceptance tests cover positive relevance, semantic denial, no model-created auto-approval/grants, zero-budget behavior, deterministic violation precedence, stale/invalid/partial/error findings, missing original-task citations, incomplete evidence, fixed/dynamic parity of assessment logic, and real runtime reviewer enforcement. Run:

```bash
cd 6101-Agent-Harness
../.venv/bin/python -m pytest -q tests/test_semantic_policy.py tests/test_r4_assessor.py tests/test_scope_policy.py
```

The [request example](contracts/request.example.json) and [stub response](contracts/response.example.json) are synthetic fixtures, not benchmark evidence. Regenerate schemas/examples/demo with `python -m src.r3_artifacts --overwrite`; the demo remains the explicit stub/rules ablation. Use the banking guide's fresh semantic-version run directories for live pilots and evaluation.
