# tests/test_pipeline.py
import sys
sys.path.insert(0, r"E:\6101\6101-agent-harness")

from unittest.mock import MagicMock
from src.pipeline import build_pipeline
from src.risk_based_policy import RiskBasedPolicy
from src.tool_risk import load_tool_risk_metadata


class MockReviewer:
    def approve(self, gate_input):
        return True
    def deny(self, gate_input):
        return False


def test_build_pipeline_returns_agent_pipeline():
    md = load_tool_risk_metadata("src/tool_risk_metadata.yaml")
    policy = RiskBasedPolicy(md)
    reviewer = MockReviewer()
    mock_client = MagicMock()
    pipeline = build_pipeline(
        model="qwen3:14b",
        policy=policy,
        k=5,
        reviewer=reviewer,
        tool_risk_metadata=md,
        system_prompt="You are a banking assistant.",
        client=mock_client,
    )
    assert pipeline is not None
    assert pipeline.max_turns == 20
    assert pipeline.initial_k == 5


def test_build_pipeline_element_order():
    md = load_tool_risk_metadata("src/tool_risk_metadata.yaml")
    policy = RiskBasedPolicy(md)
    reviewer = MockReviewer()
    mock_client = MagicMock()
    pipeline = build_pipeline(
        model="qwen3:14b",
        policy=policy,
        k=5,
        reviewer=reviewer,
        tool_risk_metadata=md,
        client=mock_client,
    )
    assert type(pipeline).__name__ == "GatedAgentPipeline"
    assert type(pipeline.agent).__name__ == "OllamaToolAgent"
    assert pipeline.policy is policy
    assert pipeline.reviewer is reviewer
