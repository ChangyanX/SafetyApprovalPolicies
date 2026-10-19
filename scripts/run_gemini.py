"""Run one clean or attacked AgentDojo task through the Gemini Developer API."""
import argparse
import json
import re
import sys
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def expected_traces(args, is_dos=False):
    """Only inspect this invocation's episodes, including attack feasibility."""
    base = args.logdir / args.model / args.suite
    if not args.attack:
        return [base / args.user_task / "none/none.json"]
    paths = [base / args.user_task / args.attack / f"{args.injection_task}.json"]
    if not is_dos:
        paths.append(base / args.injection_task / "none/none.json")
    return paths


def validate_traces(paths):
    failures = []
    for path in paths:
        try:
            result = json.loads(path.read_text())
            if result.get("error"):
                failures.append(f"{path}: recorded execution/API error")
            elif not all(isinstance(result.get(key), bool) for key in ("utility", "security")):
                failures.append(f"{path}: missing completed evaluation")
        except (OSError, ValueError):
            failures.append(f"{path}: missing or unreadable trace")
    return failures


def main(argv=None):
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    parser.add_argument("--suite", default="workspace")
    parser.add_argument("--user-task", default="user_task_0")
    parser.add_argument("--benchmark-version", default="v1.2.2")
    parser.add_argument("--logdir", type=Path, help="Defaults to runs/first_clean_run or runs/first_attacked_run")
    parser.add_argument("--attack", help="Registered AgentDojo attack, e.g. important_instructions")
    parser.add_argument("--injection-task", help="One attacker objective, e.g. injection_task_0")
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate local pipeline/task without API calls or a key")
    parser.add_argument("--list-models", action="store_true", help="List models available through your API key, then exit")
    args = parser.parse_args(argv)
    args.model = args.model.removeprefix("models/")
    if not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", args.model):
        parser.error("--model must be a Gemini model ID, e.g. gemini-3.8-flash")
    if args.logdir is None:
        args.logdir = ROOT / "runs" / ("first_attacked_run" if args.attack else "first_clean_run")
    if args.check and args.list_models:
        parser.error("--check and --list-models cannot be combined")
    if bool(args.attack) != bool(args.injection_task):
        parser.error("Provide --attack and --injection-task together.")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not args.check and (not key or key == "replace_with_your_key"):
        parser.error("Set GEMINI_API_KEY in the project .env file (copy .env.example first).")

    from google import genai
    from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig
    from gemini_adapter import SignedGoogleLLM
    from agentdojo.benchmark import benchmark_suite_without_injections, benchmark_suite_with_injections
    from agentdojo.attacks.attack_registry import ATTACKS, load_attack
    from agentdojo.models import MODEL_NAMES
    from agentdojo.logging import OutputLogger
    from agentdojo.task_suite.load_suites import get_suite

    with genai.Client(api_key=key if not args.check else "offline-check", vertexai=False) as client:
        if args.list_models:
            for model in client.models.list():
                print(model.name)
            return
        llm = SignedGoogleLLM(args.model, client=client, max_tokens=8192)
        llm.name = args.model
        pipeline = AgentPipeline.from_config(PipelineConfig(
            llm=llm, model_id=None, defense=None,
            system_message_name=None, system_message=None,
        ))
        try:
            suite = get_suite(args.benchmark_version, args.suite)
            user_task = suite.get_user_task_by_id(args.user_task)
        except (KeyError, ValueError) as exc:
            parser.error(f"Invalid benchmark version, suite or user task: {exc}")
        attacker = None
        if args.attack:
            if args.attack not in ATTACKS:
                parser.error(f"Unknown attack {args.attack!r}. Options: {', '.join(sorted(ATTACKS))}")
            try:
                suite.get_injection_task_by_id(args.injection_task)
            except (KeyError, ValueError) as exc:
                parser.error(f"Invalid injection task: {exc}")
            # Upstream attack templates need a prose name for newer model IDs.
            MODEL_NAMES.setdefault(args.model, "AI model developed by Google")
            attacker = load_attack(args.attack, suite, pipeline)
            try:
                attacker.get_injection_candidates(user_task)
            except ValueError as exc:
                parser.error(str(exc))
            if attacker.is_dos_attack and args.injection_task != next(iter(suite.injection_tasks)):
                parser.error("This upstream DoS attack uses only the suite's first injection task.")
            print(f"Attack: {args.attack}; injection task: {args.injection_task}")
        print(f"Model: {args.model}; suite: {args.suite}; task: {args.user_task}; benchmark: {args.benchmark_version}")
        if args.check:
            print("Local setup OK. No API request made; model access and live tool calling remain unverified.")
            return
        args.logdir.mkdir(parents=True, exist_ok=True)
        with OutputLogger(str(args.logdir)):
            if attacker is None:
                results = benchmark_suite_without_injections(
                    pipeline, suite, logdir=args.logdir, force_rerun=args.force_rerun,
                    user_tasks=[args.user_task], benchmark_version=args.benchmark_version,
                )
            else:
                results = benchmark_suite_with_injections(
                    pipeline, suite, attacker, logdir=args.logdir,
                    force_rerun=args.force_rerun, user_tasks=[args.user_task],
                    injection_tasks=[args.injection_task],
                    benchmark_version=args.benchmark_version,
                )
        failures = validate_traces(expected_traces(args, bool(attacker and attacker.is_dos_attack)))
        print(f"Traces: {args.logdir.resolve()}")
        if failures:
            print("Run incomplete; do not interpret returned scores as a completed benchmark.", file=sys.stderr)
            for failure in failures:
                print(failure, file=sys.stderr)
            print("Inspect the trace error and retry with --force-rerun after resolving it.", file=sys.stderr)
            return 1
        print(results)
        print("Selected episode traces contain completed evaluations and no recorded errors.")
        print("These are upstream benchmark results, not the project's TCR@k or approval-policy evaluation.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
