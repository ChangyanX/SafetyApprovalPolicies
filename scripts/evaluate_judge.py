"""Evaluate a user-supplied, per-call authorization JSONL dataset."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from src.judge_types import JudgeInput
from src.llm_judge import JudgeConfig, LocalLLMJudge


def summarize(rows):
    """Positive = unauthorized. Abstentions are excluded AND explicitly counted."""
    evaluated = [r for r in rows if r["status"] == "ok" and r["prediction"] in ("authorized", "unauthorized")]
    tp = sum(r["label"] == "unauthorized" and r["prediction"] == "unauthorized" for r in evaluated)
    fp = sum(r["label"] == "authorized" and r["prediction"] == "unauthorized" for r in evaluated)
    fn = sum(r["label"] == "unauthorized" and r["prediction"] == "authorized" for r in evaluated)
    tn = sum(r["label"] == "authorized" and r["prediction"] == "authorized" for r in evaluated)
    def ratio(a, b):
        return a / b if b else None
    scores = [r["risk_score"] for r in evaluated]
    bins = [sum(i / 5 <= s < (i + 1) / 5 or (i == 4 and s == 1) for s in scores) for i in range(5)]
    return {
        "n": len(rows), "evaluated": len(evaluated), "abstentions": len(rows) - len(evaluated),
        "coverage": ratio(len(evaluated), len(rows)), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn), "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "structured_output_success_rate": ratio(sum(r["schema_valid"] for r in rows), len(rows)),
        "risk_histogram": {"edges": [0, .2, .4, .6, .8, 1], "counts": bins},
        "risk_mean": mean(scores) if scores else None,
        "latency_mean_ms": mean(r["trace"]["latency_ms"] for r in rows) if rows else None,
        "latency_max_ms": max((r["trace"]["latency_ms"] for r in rows), default=None),
        "reported_total_tokens": sum(r["trace"]["total_tokens"] or 0 for r in rows),
        "token_usage_available_calls": sum(r["trace"]["total_tokens"] is not None for r in rows),
        "abstentions_by_label": dict(Counter(r["label"] for r in rows if r not in evaluated)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--config", type=Path, help="Optional JudgeConfig JSON, no API key")
    args = parser.parse_args()
    config = JudgeConfig.model_validate_json(args.config.read_text(encoding="utf-8")) if args.config else JudgeConfig.from_env()
    judge = LocalLLMJudge(config, prompt_path=args.prompt)
    rows = []
    ids = set()
    for line in args.data.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        if case["authorization"] not in ("authorized", "unauthorized") or case["id"] in ids:
            raise ValueError("Expected unique case ids and explicit per-call authorization labels")
        ids.add(case["id"])
        result = judge.assess(JudgeInput.model_validate(case["input"]))
        # Never write original input, model rationale, server exceptions, or endpoint.
        rows.append(dict(id=case["id"], label=case["authorization"], status=result.status,
                         prediction=result.assessment.authorization,
                         risk_score=result.assessment.risk_score,
                         schema_valid=result.schema_valid,
                         trace=result.trace.model_dump()))
    args.output.write_text(json.dumps({"summary": summarize(rows), "cases": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summarize(rows), indent=2))


if __name__ == "__main__":
    main()
