"""Check dispatch and error reporting without credentials or network requests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_gemini


class RunnerTest(unittest.TestCase):
    def test_dispatch(self):
        for attack in (False, True):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as directory:
                argv = ["--model", "models/gemini-3.8-flash", "--logdir", directory]
                if attack:
                    argv += ["--attack", "important_instructions", "--injection-task", "injection_task_0"]
                with patch.dict("os.environ", {"GEMINI_API_KEY": "offline-test"}), \
                     patch("agentdojo.benchmark.benchmark_suite_without_injections") as clean, \
                     patch("agentdojo.benchmark.benchmark_suite_with_injections") as attacked, \
                     patch.object(run_gemini, "validate_traces", return_value=[]) as validate:
                    self.assertEqual(run_gemini.main(argv), 0)
                    selected, unused = (attacked, clean) if attack else (clean, attacked)
                    selected.assert_called_once()
                    unused.assert_not_called()
                    self.assertEqual(selected.call_args.kwargs["user_tasks"], ["user_task_0"])
                    if attack:
                        self.assertEqual(selected.call_args.kwargs["injection_tasks"], ["injection_task_0"])
                    self.assertEqual(len(validate.call_args.args[0]), 2 if attack else 1)

    def test_trace_failure_and_legitimate_task_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "trace.json"
            self.assertTrue(run_gemini.validate_traces([p]))
            p.write_text(json.dumps({"utility": False, "security": True, "error": "503"}))
            self.assertTrue(run_gemini.validate_traces([p]))
            p.write_text(json.dumps({"utility": False, "security": True, "error": None}))
            self.assertEqual(run_gemini.validate_traces([p]), [])

    def test_incomplete_run_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict("os.environ", {"GEMINI_API_KEY": "offline-test"}), \
             patch("agentdojo.benchmark.benchmark_suite_without_injections"):
            self.assertEqual(run_gemini.main(["--logdir", directory]), 1)

    def test_unpaired_attack_rejected(self):
        with self.assertRaises(SystemExit) as result:
            run_gemini.main(["--attack", "important_instructions"])
        self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
