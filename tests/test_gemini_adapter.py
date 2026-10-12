import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from google.genai import types
from gemini_adapter import SignedGoogleLLM


class SignedHistoryTest(unittest.TestCase):
    def test_round_trip_and_episode_reset(self):
        signed = types.Content(role="model", parts=[
            types.Part(text="Checking", thought_signature=b"text-signature"),
            types.Part(function_call=types.FunctionCall(name="get_current_day", args={}),
                       thought_signature=b"call-signature"),
            types.Part(function_call=types.FunctionCall(name="other_lookup", args={})),
        ])
        response = types.GenerateContentResponse(candidates=[types.Candidate(content=signed)])
        initial = [{"role": "user", "content": [{"type": "text", "content": "What day?"}]}]
        llm = SignedGoogleLLM("test", client=object())
        runtime = SimpleNamespace(functions={})
        with patch("gemini_adapter.chat_completion_request", return_value=response) as request:
            _, _, _, history, state = llm.query("q", runtime, None, initial, {})
            for call in history[-1]["tool_calls"]:
                history.append({"role": "tool", "tool_call": call, "content": "Monday", "error": None})
            llm.query("q", runtime, None, history, state)
            sent = request.call_args.args[2]
            self.assertEqual(sent[1], signed)
            self.assertEqual(len(sent[2].parts), 2)
            self.assertTrue(request.call_args.args[3].automatic_function_calling.disable)
            llm.query("q", runtime, None, initial, state)
            self.assertEqual(len(request.call_args.args[2]), 1)
            history[1]["tool_calls"][0].args["changed"] = True
            with self.assertRaisesRegex(ValueError, "modified"):
                llm.query("q", runtime, None, history, state)


if __name__ == "__main__":
    unittest.main()
