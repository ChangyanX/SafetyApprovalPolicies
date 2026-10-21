# 6101 Agent Harnesses

The active study is **banking only**, with $k\in\{0,1,3,5,7,9\}$. Read the [banking run and submission guide](../docs/BANKING_EVALUATION_GUIDE.md) for current diagrams, equations, exact commands and deliverables, and the [readiness audit](../docs/BANKING_READINESS_AUDIT.md) for validation and limitations.

Use the root virtual environment and dependency lock. From this directory:

```bash
source ../.venv/bin/activate
export PYTHONDONTWRITEBYTECODE=1
python -m pytest -q
python test_r5_logger.py
python test_r5_cost_tracker.py
python test_r5_metrics.py
python -m src.experiment_runner --suite banking --output runs/banking-plan.csv
python -m src.run_experiments --manifest runs/banking-plan.csv \
  --output-dir runs/banking-evaluation --all --validate-only
python -m src.run_experiments --check --model qwen3:14b
```

The last command requires a running local Ollama server and downloaded model. It makes no benchmark calls. Do the guide's matched pilot before running the full manifest.

Current execution uses `GatedAgentPipeline` through `build_pipeline`, with a fresh pipeline/environment/budget for each manifest row. Supply `suite_name='banking'` when constructing a pipeline directly. Full-approve and full-escalate share this executor with the original scope policy. `hybrid_llm` and `hybrid_llm_fixed` wire R4 with policy usage records; eligible findings can deny unresolved conflicts or raise review relevance, but cannot create grants, override deterministic checks or bypass independent review. See [the combined-policy specification](../docs/R3_R4_POLICY.md).

Use `src.r3_compare` and `src.banking_report` for native connected logs. `src.gate`, `src.metrics`, `src.analyze_results`, `ExperimentLogger` and `CostTracker` retain their standalone/legacy interfaces for tests and old logs; their schemas are not the connected runner's schema. Raw clean `security=True` must never be interpreted as attack success or general safety.

No full live evaluation or completed report/presentation is claimed. Both must be generated from the frozen experiment and inspected evidence described in the guide.
