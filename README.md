# Safety Approval Policies for Agent Harnesses

Review budget grid: $k\in\{0,1,3,5,7,9\}$.

Current scope: **banking only**, per the user's direction on 21 October 2026. AgentDojo is pinned to `0.1.35`, benchmark `v1.2.2`. Local `qwen3:14b` is selected for agent execution, semantic policy assessment and simulated review, with separate prompts/contexts.

Start with the [banking evaluation and submission guide](docs/BANKING_EVALUATION_GUIDE.md). It contains the current Mermaid policy diagrams and justification, LaTeX equations, environment setup, pilot/full-run/resume/analysis commands, required report evidence and presentation checklist. The [readiness audit](docs/BANKING_READINESS_AUDIT.md) records integration fixes, validation and remaining limitations.

## Status

The banking evaluation workflow is implemented and offline-validated: connected gate, required baselines, combined R3/R4 policies, separate policy runs and matched comparison exports. Latest validation: 233 harness tests passed and one opt-in live test skipped. Run model preflight and current-version development pilots before the full evaluation. The latest model availability check from this session could not reach the local Ollama endpoint; verify it in the experiment terminal. Empirical conclusions require the completed matched evaluation and inspected trajectories.

The required policies are full-approve, full-escalate, and our scope-aware policy. The CLI now defaults to banking with both baselines, `hybrid_llm`, and its fixed allocation comparator. Metadata-only and explicit stub variants remain available. Other domains remain supported by shared library code and regression tests, but are outside this study.

R4 is **decision-effective** in `hybrid_llm` and `hybrid_llm_fixed`: validated task-grounded conflicts can deny unresolved calls, while supported scope and operation can raise review relevance. Deterministic checks remain authoritative; R4 cannot create grants or execute a call without independent review. See [the combined-policy specification](docs/R3_R4_POLICY.md). The policy is a conservative exact-grant/bounded-banking-rule implementation, not a general natural-language authorization parser. See the guide for its limitations and experimental implications.

## Execution path

`src.experiment_runner` freezes manifests → `src.run_experiments` builds fresh episodes → `src.pipeline` / `src.gated_runtime` gate every valid tool proposal → official AgentDojo evaluator scores actual invocations → `src.r3_compare` validates results → `src.banking_report` exports curves, coverage, HITL totals, component costs and trajectory candidates.

These modules live inside `6101-Agent-Harness/`; run them from that directory. `src.gate` is a legacy standalone fixture and `src.analyze_results` / `src.metrics` consume legacy R5 logs. They are not the connected banking evaluation path. Root `scripts/run_gemini.py` is a separate stock-pipeline smoke runner.

## Requirements and metrics

The [course handout](AI6101%20Group%20Project%201%20-%20Safety%20Approval%20Policies%20for%20Agent%20Harnesses.pdf), §§2–4, requires an integrated gate, an original policy, both baselines, TCR curves, total HITL, agent/policy/reviewer API cost, both failure classes with concrete trajectories, escalation-value analysis, and a 10-minute presentation plus 5-minute Q&A, submitted through GitHub. Reviewer context must exclude oracle labels and attack annotations.

With attacked utility $U_i$, specified attack success $J_i$, and actual reviewer use $E_i$, the existing project operationalization is

$$
\widehat{\operatorname{TCR}}_{\mathrm{AD}}@k
=\frac{1}{N_{\mathrm{valid}}}\sum_{i\in\mathcal V}U_i(1-J_i),\qquad E_i\le k.
$$

This proxy does not certify the absence of every unauthorized call. Report attacked utility and attack success alongside it, clean utility separately, and coverage/error bounds. Raw attacked `security=True` means attack success; clean `security=True` is a sentinel. Actual invocations are preserved for audit. Both utility-success and safe-success HITL totals are exported with cohort sizes. Local API dollar charge is zero; tokens, unknown usage and excluded hardware cost must be disclosed.

## Quick offline validation

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-evaluation.lock
source .venv/bin/activate
export PYTHONDONTWRITEBYTECODE=1
python -m unittest discover -s tests -v
cd 6101-Agent-Harness
python -m pytest -q
python test_r5_logger.py
python test_r5_cost_tracker.py
python test_r5_metrics.py
python -m src.experiment_runner --suite banking --output runs/banking-plan.csv
python -m src.run_experiments --manifest runs/banking-plan.csv \
  --output-dir runs/banking-evaluation --all --validate-only
```

Planning/validation make no model calls. Use the guide's matched pilot before its full evaluation commands. Always use `--all` for frozen comparisons; the executor otherwise selects its first 10 rows. `runs/` is eligible for Git tracking so frozen experiment evidence can be submitted. Add the intended run directories explicitly; removing the ignore rule does not stage or commit them. Credentials and local environments remain ignored.

## Source precedence

The latest user scope and course handout govern this study. This README, current guide and audit describe the active implementation. `R3/` contains earlier designs, decisions and experiments, including superseded four-suite scope and commands. Preserve them as historical context; they do not override banking-only execution or prove a benchmark was completed. The five-role ownership remains gate/budget (R1), baselines/reviewer (R2), scope/allocation (R3), semantic assessor (R4), and evaluation/audit/analysis (R5).
