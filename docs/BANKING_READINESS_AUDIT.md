# Banking integration and deliverable readiness audit

Date: 21 October 2026. Scope: the merged repository, its connected execution path, shared regression tests, the two-page course handout and the internal project guidelines. Current user scope is banking only. See [the operational guide](BANKING_EVALUATION_GUIDE.md) for all commands and policy diagrams.

## Verdict

**Before fixes:** not ready for trustworthy full evaluation or automatic generation of the handout evidence.

**After fixes:** offline integration is validated and a reproducible banking evaluation/export path exists. Ready to attempt the live pilot; full-run promotion remains conditional on that pilot. The local Ollama endpoint did not respond during this review. No live Qwen benchmark, final experimental claim, finished report or presentation is asserted.

The user confirmed local `qwen3:14b` for agent, assessor and reviewer. All three use separate requests/contexts. Shared model weights can cause correlated failures.

## Discrepancies and resolutions

| Finding | Resolution |
|---|---|
| Root and harness README described superseded all-domain scope and unfinished integration | Replaced active documentation with banking-only status, current commands and source precedence; retained `R3/` as historical material |
| Default planner selected all domains and only baselines plus metadata policy, omitting the scope-aware policy | CLI now defaults to banking, both required baselines, `hybrid_llm`, and `hybrid_llm_fixed`; task/attack-objective cohort selectors added; general library API compatibility retained |
| Live runner always built the scope policy with a stub despite implemented R4 code | Explicit live labels now instantiate `LocalR3Assessor` using the actual model client; live policy construction without an assessor is rejected; stub labels remain explicit |
| R4 output costs/statuses were absent from live usage | Per-assessment traces in `assessor.jsonl`; actual policy API attempts in `usage.jsonl`; unavailable preflight assessments do not masquerade as paid calls; local Qwen thinking disabled in the connected assessor configuration |
| R4 prompt content omitted from frozen source fingerprints | Fingerprints now include all `src/prompts/*.txt`, runtime Python sources, tool metadata and reviewer prompt |
| Legacy R5 analyzer expected `episode_results.jsonl`, `gate_decisions.jsonl`, `cost_calls.jsonl`; runner emitted native episode/audit/usage files | Added `src.banking_report`, directly consuming frozen native runner files and reusing `r3_compare` validation; legacy interfaces retained and clearly identified |
| Combining clean and attacked rows would invert clean security meaning and contaminate TCR | Native analysis separates condition groups; clean security sentinel never becomes attack success; attacked TCR uses official utility and attack success with a documented proxy limitation |
| Legacy HITL aggregation could collapse repeated task identities and used an ambiguous success cohort | Native exports aggregate consultations by unique episode; both utility-success and safe-success totals/cohort sizes are explicit, alongside all-observed reviews |
| Reviewer summaries could duplicate HTTP-attempt cost totals | Only native `api_attempt` records enter cost aggregation; unknown costs/tokens remain visible, with explicit zero-call deterministic components |
| Repeated denial suppression affected full-escalate, violating review-every-valid-proposal baseline semantics | Suppression now belongs to the scope-aware policy only; full-escalate reviews repeated valid proposals while budget remains; regression expectation corrected |
| Reviewer logs lacked proposed arguments, stable call identity and exact request attempts | Verdict logs now include identity/arguments/initial prompt; `reviewer_requests.json` preserves exact wire requests including repair/retry requests |
| Swallowed usage callback errors could produce apparently successful but uncosted episodes | Reviewer usage audit failures and assessor trace-persistence failures mark the episode as an error; result scoring fields become unknown |
| Executor completed with exit status zero even when episodes failed | CLI returns nonzero for errored selections; analyzer returns nonzero for incomplete/audit-invalid or unmatched/inadequate studies unless explicitly exporting diagnostics |
| No model-free manifest validation CLI | Added `--validate-only`; no endpoint calls or output-directory creation |
| Executor could select other domains from an old mixed manifest without an explicit suite flag | Default execution selection is banking; other suite support requires an explicit suite selection |
| Smoke command defaulted to all suites | Banking is now the smoke default and `--suite banking` is documented |
| Sanity test expected stock `AgentPipeline` after factory migrated to repeated custom runtime | Test now verifies `BasePipelineElement` compatibility and the actual `GatedAgentPipeline` class |
| Figure dependency absent from harness requirements; transitive environment not frozen | Added matplotlib and root `requirements-evaluation.lock` containing the tested dependency set |
| Failure mining and escalation evidence were not connected to native logs | Exports now include failure candidates with trace paths and blank confirmation fields, review-by-tool outcomes, assessment statuses and escalation tables |

## Verified behavior and commands

Validation was performed in the repository-local Python 3.12 environment installed from the project requirements, then frozen in the evaluation lock.

- Harness regression suite: **194 passed, 1 skipped, 30 subtests passed**. The skipped case is the opt-in live local-model assessor test, not an offline integration failure.
- Root Gemini runner/adapter tests: **5 passed**. These validate their separate stock-runner path, not gated model performance.
- Explicit legacy R5 logger, cost and metric scripts passed. They are not collected as pytest test functions and retain their old schema semantics.
- Banking offline smoke: **10 scripted integration episodes**, five existing baseline/stub policies, clean plus fixed attack. Real environments, tools, attack setup and official evaluators were used; actors and reviewer were scripted. These results are tagged `offline_test` and rejected by benchmark comparison/reporting.
- A full **9,600-row banking-only manifest** was generated and every row validated without model calls. The documented smaller pilot arithmetic and identity selection are also covered by tests.
- Fake-provider integration verified that `hybrid_llm` actually invokes R4, passes no attack-annotation fields, records policy API usage and persists assessor traces. This is transport/schema evidence, not model-quality evidence.
- Native report exports and plots were generated from synthetic schema-test records in a temporary directory. Clean sentinel direction, attacked TCR, both HITL cohorts, missing/error bounds, consultation-summary deduplication, offline-fixture rejection and output-directory protection are regression tested. Chart layout was visually inspected; these synthetic charts are not submitted as benchmark results.
- `git diff --check` passed. Mermaid source and LaTeX display delimiters were checked; diagrams describe current code branches, including advisory R4. No external Mermaid rendering or live model validation is claimed.

Exact setup, tests, smoke, manifest generation, live preflight, pilots, full sweep, resume and export commands are in [the guide](BANKING_EVALUATION_GUIDE.md). Temporary smoke/plot-test artifacts are outside the submission tree and are not empirical project evidence.

## Remaining limitations and evidence gaps

1. **Live readiness:** start local Ollama, ensure `qwen3:14b` is available, and pass the matched live pilot. Native tool calling, schema response quality, model latency/context limits and real usage need live validation. The endpoint was unavailable during this audit.
2. **Scope coverage:** exact grants and bounded prerequisite/rent rules are implemented; arbitrary banking natural language remains unresolved and relies on conservative relevance/review handling. This can produce substantial utility loss. It is a limitation of the current original policy, not evidence that all banking tasks have been solved.
3. **Advisory R4:** its findings cannot authorize calls or change current decisions/allocation scores. Live assessor overhead is measured, but semantic decision improvement is not implemented or claimed. A stronger policy would require a new version, development-only tuning and new matched evaluation.
4. **Strict safety metric:** official AgentDojo attack goals do not label every unauthorized call. The current accepted project metric is AgentDojo-based TCR; executed-call audit supplements it. Do not relabel attack-goal failure as proof that every action was authorized.
5. **Experiment design:** freeze budget grid, coefficients, model digest, limits, attacks, task split and retry protocol after development. The guide uses all 16 banking identities descriptively and a separately analyzed 13-task held-out subset. Shared attack/task/repeat dependencies require care with uncertainty and significance claims; the exporter does not produce confidence intervals.
6. **Model provenance:** automatic `config.json` weights digest remains empty. Capture full tags/digest, model file, Ollama version and hardware with the guide's provenance commands. Runtime hashes alone cannot establish identical model weights.
7. **Empirical deliverables:** full model results, genuine curves, confirmed representative failures, causal/qualitative escalation-value discussion, report and presentation are still to be produced. Machine completeness checks are necessary but do not certify a finished submission.
8. **Manual failure classification:** an attack following reviewer approval must not automatically be called an auto-approval policy false negative. A utility failure alone does not prove over-conservatism. Confirm decisive calls from trajectories; do not invent examples to fill the handout categories.
9. **Local API accounting:** zero API dollars excludes compute/electricity. Report tokens, unknown token counts and component inference overhead. R4 has a single attempt; agent/reviewer default to one transport attempt, with at most one reviewer formatting repair per consultation.
10. **Submission packaging:** `runs/` is ignored by Git. Preserve full audit/provenance and copy publishable results, figures, curated cases, report and slides into the submitted artifact tree. Old local traces and historical R3 documents are not evidence of the new frozen run.

No push, PR, live full evaluation or external publication was performed by this audit.
