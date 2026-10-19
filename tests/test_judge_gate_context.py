from src.gate import GateElement
from src.types import Decision, GateOutput


def test_gate_passes_original_query_when_user_task_missing():
    class CapturingPolicy:
        def decide(self, value):
            self.value = value
            return GateOutput(decision=Decision.AUTO_DENY)
    policy = CapturingPolicy()
    gate = GateElement(policy, None, 0, {})
    gate.query("Show my balance", None, messages=[{
        "role": "assistant", "tool_calls": [{"id": "1", "function": "get_balance", "args": {}}],
    }], extra_args={})
    assert policy.value.user_task_text == "Show my balance"
