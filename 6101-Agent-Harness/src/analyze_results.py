
"""Analyze R5 experiment results and automatically generate charts.

Reads:
    gate_decisions.jsonl
    episode_results.jsonl
    cost_calls.jsonl

Produces:
    metrics_summary.csv
    hitl_load.csv
    tcr_at_k.csv
    analysis_warnings.txt
    tcr_at_k.png
    hitl_load_vs_k.png
    utility_vs_security.png
    k_sweep.png
    cost_analysis.png

Usage:
    python -m src.analyze_results
    python -m src.analyze_results --input-dir runs --output-dir runs/analysis
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .metrics import calculate_metrics
except ImportError:
    from metrics import calculate_metrics


COMPONENTS = ("agent", "policy", "reviewer")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL records and skip invalid lines."""
    records = []

    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
                else:
                    print(
                        f"WARNING: {path}:{line_number} "
                        "is not a JSON object."
                    )
            except json.JSONDecodeError as exc:
                print(
                    f"WARNING: Cannot parse "
                    f"{path}:{line_number}: {exc}"
                )

    return records


def find_log_files(input_dir: Path):
    """Find logs, excluding the analysis output directory."""
    def is_input_log(path: Path) -> bool:
        relative = path.relative_to(input_dir)
        return "analysis" not in relative.parts

    gate_files = sorted(
        p for p in input_dir.rglob("gate_decisions.jsonl")
        if is_input_log(p)
    )
    episode_files = sorted(
        p for p in input_dir.rglob("episode_results.jsonl")
        if is_input_log(p)
    )
    cost_files = sorted(
        p for p in input_dir.rglob("cost_calls.jsonl")
        if is_input_log(p)
    )

    return gate_files, episode_files, cost_files


def load_all_records(input_dir: Path):
    """Load logs and retain source-file information."""
    gate_records = []
    episode_records = []
    cost_records = []
    warnings = []

    gate_files, episode_files, cost_files = find_log_files(input_dir)

    groups = [
        ("gate", gate_files, gate_records),
        ("episode", episode_files, episode_records),
        ("cost", cost_files, cost_records),
    ]

    for record_type, files, destination in groups:
        for path in files:
            for record in read_jsonl(path):
                record.setdefault("_source_file", str(path))
                destination.append(record)

        if not files:
            warnings.append(
                f"No {record_type} log files found under {input_dir}."
            )

    return gate_records, episode_records, cost_records, warnings


def get_policy_k(record: dict[str, Any]):
    """Return the policy and budget grouping key."""
    policy = record.get("policy")
    k = record.get("k")

    if policy is None or k is None:
        return None

    try:
        return str(policy), int(k)
    except (TypeError, ValueError):
        return None


def to_number(value):
    """Safely convert a value to float."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def safe_ratio(numerator, denominator):
    """Return a ratio, or None when it cannot be calculated."""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    """Write a CSV file."""
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        if not fieldnames:
            file.write("")
            return

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def generate_charts(
    output_dir: Path,
    summary_rows: list[dict[str, Any]],
    gate_records: list[dict[str, Any]],
    warnings: list[str],
) -> list[str]:
    """Generate all available charts from actual analysis results."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        warnings.append(
            "matplotlib is not installed. CSV files were generated, "
            "but charts were skipped. Install with: "
            "python -m pip install matplotlib"
        )
        return []

    generated = []

    def save_chart(filename: str):
        path = output_dir / filename
        plt.tight_layout()
        plt.savefig(path, dpi=180, bbox_inches="tight")
        plt.close()
        generated.append(filename)
        print(f"[OK] Generated chart: {path}")

    def group_by_policy(rows):
        groups = defaultdict(list)
        for row in rows:
            groups[str(row.get("policy", "unknown"))].append(row)
        return groups

    def line_chart(
        filename,
        title,
        x_label,
        y_label,
        field,
        y_percent=False,
    ):
        """Draw a line chart grouped by policy."""
        valid = [
            row for row in summary_rows
            if to_number(row.get("k")) is not None
            and to_number(row.get(field)) is not None
        ]

        if not valid:
            warnings.append(
                f"{filename} was skipped: no valid '{field}' values."
            )
            return

        plt.figure(figsize=(8, 5))

        for policy, rows in group_by_policy(valid).items():
            rows = sorted(rows, key=lambda r: to_number(r["k"]))
            plt.plot(
                [to_number(r["k"]) for r in rows],
                [to_number(r[field]) for r in rows],
                marker="o",
                label=policy,
            )

        plt.title(title)
        plt.xlabel(x_label)
        plt.ylabel(y_label)

        if y_percent:
            plt.ylim(0, 1)

        plt.grid(True, alpha=0.3)
        plt.legend()
        save_chart(filename)

    # 1. TCR@k curve.
    # This uses the definition currently implemented in metrics.py.
    line_chart(
        "tcr_at_k.png",
        "TCR@k by Policy",
        "Approval Budget (k)",
        "TCR@k",
        "TCR_at_k",
        y_percent=True,
    )

    # 2. Human intervention load.
    line_chart(
        "hitl_load_vs_k.png",
        "Human Intervention Load vs. Budget",
        "Approval Budget (k)",
        "Reviews per Successful Task",
        "HITL_load_per_successful_task",
    )

    # 3. Utility vs Security comparison.
    # Task completion rate is calculated using the current metrics output.
    utility_field = "task_completion_rate"
    security_field = "unauthorized_action_rate"

    utility_values = []
    security_values = []

    for row in summary_rows:
        total = to_number(row.get("total_episodes"))
        completed = to_number(
            row.get("completed_tasks_with_known_safety_label")
        )

        # Do not treat unknown safety labels as safe.
        known = to_number(row.get("episodes_with_known_safety_label"))
        unauthorized = to_number(
            row.get("unauthorized_tool_call_count")
        )

        utility = safe_ratio(completed, total)
        security = safe_ratio(unauthorized, known)

        # If the exact unauthorized count is unavailable, do not guess it.
        utility_values.append(utility)
        security_values.append(security)

    utility_security_rows = []
    for index, row in enumerate(summary_rows):
        utility_security_rows.append({
            **row,
            utility_field: utility_values[index],
            security_field: security_values[index],
        })

    valid = [
        row for row in utility_security_rows
        if row[utility_field] is not None
        and row[security_field] is not None
    ]

    if valid:
        labels = [
            f"{r.get('policy', 'unknown')}\nk={r.get('k', '?')}"
            for r in valid
        ]
        positions = list(range(len(valid)))
        width = 0.38

        plt.figure(figsize=(max(8, len(valid) * 1.1), 5))
        plt.bar(
            [x - width / 2 for x in positions],
            [r[utility_field] for r in valid],
            width=width,
            label="Task completion rate",
        )
        plt.bar(
            [x + width / 2 for x in positions],
            [r[security_field] for r in valid],
            width=width,
            label="Unauthorized action rate",
        )
        plt.xticks(positions, labels, rotation=30, ha="right")
        plt.ylim(0, 1)
        plt.ylabel("Rate")
        plt.title("Utility vs. Security")
        plt.legend()
        plt.grid(axis="y", alpha=0.3)
        save_chart("utility_vs_security.png")
    else:
        warnings.append(
            "utility_vs_security.png was skipped. It requires both "
            "task completion and unauthorized-action counts. Check "
            "whether metrics.py records unauthorized_tool_call_count."
        )

    # 4. Budget sweep: escalation rate and unauthorized-action rate.
    # Escalation rate = escalations / all gate decisions.
    gate_groups = defaultdict(list)
    for record in gate_records:
        key = get_policy_k(record)
        if key is not None:
            gate_groups[key].append(record)

    sweep_rows = []

    for row in summary_rows:
        policy = str(row.get("policy", "unknown"))
        k = int(row["k"])
        decisions = gate_groups.get((policy, k), [])

        if decisions:
            escalations = sum(
                1 for record in decisions
                if str(record.get("decision", "")).upper()
                in ("ESCALATE", "DECISION.ESCALATE")
            )
            escalation_rate = len(
                [r for r in decisions if r.get("decision") is not None]
            )
            escalation_rate = safe_ratio(
                escalations, escalation_rate
            )
        else:
            escalation_rate = None

        known = to_number(row.get("episodes_with_known_safety_label"))
        unauthorized = to_number(
            row.get("unauthorized_tool_call_count")
        )

        sweep_rows.append({
            **row,
            "escalation_rate": escalation_rate,
            "unauthorized_action_rate": safe_ratio(
                unauthorized, known
            ),
        })

    # Save the calculated sweep values for inspection.
    write_csv(
        output_dir / "k_sweep.csv",
        sweep_rows,
    )

    has_escalation = any(
        r["escalation_rate"] is not None for r in sweep_rows
    )
    has_unauthorized = any(
        r["unauthorized_action_rate"] is not None
        for r in sweep_rows
    )

    if has_escalation or has_unauthorized:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

        if has_escalation:
            for policy, rows in group_by_policy(sweep_rows).items():
                points = sorted(
                    [
                        r for r in rows
                        if r["escalation_rate"] is not None
                    ],
                    key=lambda r: int(r["k"]),
                )
                if points:
                    axes[0].plot(
                        [int(r["k"]) for r in points],
                        [r["escalation_rate"] for r in points],
                        marker="o",
                        label=policy,
                    )
            axes[0].set_title("Escalation Rate")
            axes[0].set_xlabel("Budget k")
            axes[0].set_ylabel("Escalations / Gate Decisions")
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)
        else:
            axes[0].set_visible(False)

        if has_unauthorized:
            for policy, rows in group_by_policy(sweep_rows).items():
                points = sorted(
                    [
                        r for r in rows
                        if r["unauthorized_action_rate"] is not None
                    ],
                    key=lambda r: int(r["k"]),
                )
                if points:
                    axes[1].plot(
                        [int(r["k"]) for r in points],
                        [r["unauthorized_action_rate"] for r in points],
                        marker="o",
                        label=policy,
                    )
            axes[1].set_title("Unauthorized Action Rate")
            axes[1].set_xlabel("Budget k")
            axes[1].set_ylabel("Unauthorized / Known Episodes")
            axes[1].legend()
            axes[1].grid(True, alpha=0.3)
        else:
            axes[1].set_visible(False)

        fig.suptitle("Budget k Sweep")
        save_chart("k_sweep.png")
    else:
        warnings.append(
            "k_sweep.png was skipped because escalation or "
            "unauthorized-action metrics are unavailable."
        )

    # 5. Cost and token analysis.
    cost_fields = [
        f"{component}_known_cost_usd"
        for component in COMPONENTS
    ]
    has_known_cost = any(
        to_number(row.get(field)) is not None
        for row in summary_rows
        for field in cost_fields
    )

    token_fields = [
        f"{component}_total_tokens"
        for component in COMPONENTS
    ]
    has_tokens = any(
        to_number(row.get(field)) is not None
        for row in summary_rows
        for field in token_fields
    )

    if has_known_cost:
        labels = [
            f"{r.get('policy', 'unknown')}\nk={r.get('k', '?')}"
            for r in summary_rows
        ]
        positions = list(range(len(summary_rows)))
        bottoms = [0.0] * len(summary_rows)

        plt.figure(figsize=(max(8, len(labels) * 1.1), 5))

        for component in COMPONENTS:
            values = [
                to_number(row.get(f"{component}_known_cost_usd")) or 0.0
                for row in summary_rows
            ]
            plt.bar(
                positions,
                values,
                bottom=bottoms,
                label=component,
            )
            bottoms = [
                bottoms[i] + values[i]
                for i in range(len(values))
            ]

        plt.xticks(positions, labels, rotation=30, ha="right")
        plt.ylabel("Known cost (USD)")
        plt.title("Known Model Cost by Policy and Budget")
        plt.legend()
        plt.grid(axis="y", alpha=0.3)
        save_chart("cost_analysis.png")

    elif has_tokens:
        labels = [
            f"{r.get('policy', 'unknown')}\nk={r.get('k', '?')}"
            for r in summary_rows
        ]
        positions = list(range(len(summary_rows)))
        bottoms = [0.0] * len(summary_rows)

        plt.figure(figsize=(max(8, len(labels) * 1.1), 5))

        for component in COMPONENTS:
            values = [
                to_number(row.get(f"{component}_total_tokens")) or 0.0
                for row in summary_rows
            ]
            plt.bar(
                positions,
                values,
                bottom=bottoms,
                label=component,
            )
            bottoms = [
                bottoms[i] + values[i]
                for i in range(len(values))
            ]

        plt.xticks(positions, labels, rotation=30, ha="right")
        plt.ylabel("Total tokens")
        plt.title("Token Usage by Policy and Budget")
        plt.legend()
        plt.grid(axis="y", alpha=0.3)
        save_chart("cost_analysis.png")
        warnings.append(
            "No known USD costs were available. cost_analysis.png "
            "shows token usage instead of monetary cost."
        )
    else:
        warnings.append(
            "cost_analysis.png was skipped: no known costs or token "
            "counts are available."
        )

    return generated


def analyze_results(
    input_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Calculate metrics, export CSVs, and generate charts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    gate_records, episode_records, cost_records, warnings = (
        load_all_records(input_dir)
    )

    if not episode_records:
        warnings.append(
            "No episode records were loaded. Metrics cannot be "
            "calculated without episode results."
        )

    episode_groups = defaultdict(list)
    for record in episode_records:
        key = get_policy_k(record)
        if key is None:
            warnings.append(
                "Episode record missing valid policy/k: "
                f"{record.get('_source_file', 'unknown source')}"
            )
            continue
        episode_groups[key].append(record)

    gate_groups = defaultdict(list)
    for record in gate_records:
        key = get_policy_k(record)
        if key is not None:
            gate_groups[key].append(record)

    cost_groups = defaultdict(list)
    unassigned_cost_records = []

    for record in cost_records:
        key = get_policy_k(record)
        if key is None:
            unassigned_cost_records.append(record)
        else:
            cost_groups[key].append(record)

    if unassigned_cost_records:
        warnings.append(
            f"{len(unassigned_cost_records)} cost records lack policy/k "
            "metadata and were excluded from per-policy metrics."
        )

    summary_rows = []
    hitl_rows = []
    tcr_rows = []

    for policy, k in sorted(episode_groups.keys()):
        episodes = episode_groups[(policy, k)]
        gates = gate_groups.get((policy, k), [])
        costs = cost_groups.get((policy, k), [])

        metrics = calculate_metrics(
            episode_records=episodes,
            gate_records=gates,
            cost_records=costs,
        )

        row = {
            "policy": policy,
            "k": k,
            **metrics,
        }

        # Flatten component cost metrics.
        component_costs = row.pop("cost_by_component", {})

        for component in COMPONENTS:
            component_records = [
                record for record in costs
                if record.get("component") == component
            ]

            input_tokens = sum(
                int(to_number(r.get("input_tokens")) or 0)
                for r in component_records
            )
            output_tokens = sum(
                int(to_number(r.get("output_tokens")) or 0)
                for r in component_records
            )

            component_metrics = component_costs.get(component, {})
            row[f"{component}_calls"] = component_metrics.get("calls", 0)
            row[f"{component}_known_cost_usd"] = (
                component_metrics.get("known_cost_usd", 0)
            )
            row[f"{component}_unknown_cost_calls"] = (
                component_metrics.get("unknown_cost_calls", 0)
            )
            row[f"{component}_input_tokens"] = input_tokens
            row[f"{component}_output_tokens"] = output_tokens
            row[f"{component}_total_tokens"] = (
                input_tokens + output_tokens
            )

        # Derive unauthorized count only when every episode has a known
        # boolean safety label. Never treat missing labels as safe.
        safety_labels = [
            record.get("unauthorized_tool_call")
            for record in episodes
        ]
        if all(isinstance(value, bool) for value in safety_labels):
            row["unauthorized_tool_call_count"] = sum(safety_labels)
        else:
            row["unauthorized_tool_call_count"] = None

        summary_rows.append(row)

        hitl_rows.append({
            "policy": policy,
            "k": k,
            "completed_tasks_with_known_safety_label":
                metrics.get("completed_tasks_with_known_safety_label"),
            "human_interventions_on_successful_tasks":
                metrics.get("human_interventions_on_successful_tasks"),
            "HITL_load_per_successful_task":
                metrics.get("HITL_load_per_successful_task"),
        })

        tcr_rows.append({
            "policy": policy,
            "k": k,
            "TCR_at_k": metrics.get("TCR_at_k"),
            "total_episodes": metrics.get("total_episodes"),
            "episodes_with_known_safety_label":
                metrics.get("episodes_with_known_safety_label"),
            "safe_completed_episodes":
                metrics.get("safe_completed_episodes"),
        })

    write_csv(output_dir / "metrics_summary.csv", summary_rows)
    write_csv(output_dir / "hitl_load.csv", hitl_rows)
    write_csv(output_dir / "tcr_at_k.csv", tcr_rows)

    generated_charts = generate_charts(
        output_dir=output_dir,
        summary_rows=summary_rows,
        gate_records=gate_records,
        warnings=warnings,
    )

    warning_path = output_dir / "analysis_warnings.txt"
    if warnings:
        warning_path.write_text(
            "\n".join(f"- {item}" for item in warnings) + "\n",
            encoding="utf-8",
        )
    elif warning_path.exists():
        warning_path.unlink()

    return {
        "gate_records": len(gate_records),
        "episode_records": len(episode_records),
        "cost_records": len(cost_records),
        "experiment_groups": len(episode_groups),
        "summary_rows": len(summary_rows),
        "generated_charts": generated_charts,
        "warnings": warnings,
        "output_dir": str(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze R5 Agent Harness experiment logs."
    )
    parser.add_argument(
        "--input-dir",
        default="runs",
        help="Directory containing experiment logs (default: runs).",
    )
    parser.add_argument(
        "--output-dir",
        default="runs/analysis",
        help="Directory for analysis outputs (default: runs/analysis).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"ERROR: Input directory does not exist: {input_dir}")
        return 1

    if input_dir == output_dir:
        print(
            "ERROR: Use a separate output directory for analysis files."
        )
        return 1

    result = analyze_results(input_dir, output_dir)

    print("\nR5 Analysis Complete")
    print("--------------------")
    print(f"Gate records:      {result['gate_records']}")
    print(f"Episode records:   {result['episode_records']}")
    print(f"Cost records:      {result['cost_records']}")
    print(f"Experiment groups: {result['experiment_groups']}")
    print(f"Summary rows:      {result['summary_rows']}")
    print(f"Charts generated:  {len(result['generated_charts'])}")
    print(f"Output directory:  {result['output_dir']}")

    for filename in result["generated_charts"]:
        print(f"  - {filename}")

    if result["warnings"]:
        print(f"\nWarnings: {len(result['warnings'])}")
        for warning in result["warnings"]:
            print(f"- {warning}")

    if result["episode_records"] == 0:
        print(
            "\nNo episode results were found. The script ran, but "
            "there are no task results to analyze yet."
        )
        return 1

    if result["summary_rows"] == 0:
        print(
            "\nEpisode records were found, but no valid policy/k groups "
            "could be created. Check the JSONL fields."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
