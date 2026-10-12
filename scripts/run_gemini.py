"""Run one clean AgentDojo task through the Gemini Developer API."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    parser.add_argument("--suite", default="workspace")
    parser.add_argument("--user-task", default="user_task_0")
    parser.add_argument("--benchmark-version", default="v1.2.2")
    parser.add_argument("--logdir", type=Path, default=ROOT / "runs/first_clean_run")
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate local pipeline/task without API calls or a key")
    parser.add_argument("--list-models", action="store_true", help="List models available through your API key, then exit")
    args = parser.parse_args()
    if args.check and args.list_models:
        parser.error("--check and --list-models cannot be combined")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not args.check and (not key or key == "replace_with_your_key"):
        parser.error("Set GEMINI_API_KEY in the project .env file (copy .env.example first).")

    from google import genai
    from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig
    from gemini_adapter import SignedGoogleLLM
    from agentdojo.benchmark import benchmark_suite_without_injections
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
        suite = get_suite(args.benchmark_version, args.suite)
        suite.get_user_task_by_id(args.user_task)
        print(f"Model: {args.model}; suite: {args.suite}; task: {args.user_task}; benchmark: {args.benchmark_version}")
        if args.check:
            print("Local setup OK. No API request made; model access and live tool calling remain unverified.")
            return
        args.logdir.mkdir(parents=True, exist_ok=True)
        with OutputLogger(str(args.logdir)):
            results = benchmark_suite_without_injections(
                pipeline, suite, logdir=args.logdir, force_rerun=args.force_rerun,
                user_tasks=[args.user_task], benchmark_version=args.benchmark_version,
            )
        print(results)
        print(f"Traces: {args.logdir.resolve()}")


if __name__ == "__main__":
    main()
