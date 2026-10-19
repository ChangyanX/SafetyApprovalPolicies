"""Opt in explicitly; a running local model and env configuration are required."""
import os

import pytest

from src.judge_types import JudgeInput
from src.llm_judge import JudgeConfig, LocalLLMJudge


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("RUN_JUDGE_INTEGRATION") != "1", reason="Local model integration is opt-in")
def test_local_model_returns_valid_assessment():
    judge = LocalLLMJudge(JudgeConfig.from_env())
    result = judge.assess(JudgeInput(
        user_task_text="Show my account balance.", tool_name="get_balance", args={},
        tool_metadata={"risk": "low", "category": "read"},
    ))
    assert result.schema_valid, result.status
    assert result.usable, result.status
