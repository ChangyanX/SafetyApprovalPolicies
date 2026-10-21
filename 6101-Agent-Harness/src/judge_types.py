"""Judge contracts; deliberately independent of approval decisions and budgets."""
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .types import GateInput


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class JudgeInput(StrictModel):
    user_task_text: str
    authorization_scope: str = ""
    tool_name: str = Field(min_length=1)
    args: dict[str, Any]
    tool_metadata: dict[str, Any] = Field(default_factory=dict)
    trajectory: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_gate(cls, value: GateInput) -> "JudgeInput":
        # R3 adds suite/episode/call fields. Explicit projection also supports R1.
        return cls(**value.model_dump(include={
            "user_task_text", "tool_name", "args", "tool_metadata", "trajectory",
        }))


class RiskAssessment(StrictModel):
    authorization: Literal["authorized", "unauthorized", "uncertain"]
    operational_risk: Literal["low", "medium", "high", "critical", "unknown"]
    risk_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    injection_suspected: bool
    context_sufficient: bool
    rationale: str = Field(min_length=1, max_length=1200)


class JudgeTrace(StrictModel):
    model: str
    prompt_sha256: str
    parameters: dict[str, Any]
    latency_ms: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    history_truncated: bool = False


class JudgeResult(StrictModel):
    status: Literal["ok", "insufficient_context", "invalid_output", "timeout", "service_error"]
    schema_valid: bool = False
    assessment: RiskAssessment
    trace: JudgeTrace

    @property
    def usable(self) -> bool:
        """Necessary, not sufficient, condition for policy use of the score."""
        return self.status == "ok" and self.schema_valid and self.assessment.context_sufficient


class RiskJudge(Protocol):
    def assess(self, value: JudgeInput | GateInput) -> JudgeResult: ...


class ScoreCalibrator(Protocol):
    """Optional future mapping fitted on held-out, per-call authorization labels.

    Keep the raw score unchanged. Version any fitted mapping and report its target,
    dataset/split and reliability metrics separately from JudgeResult.
    """
    def predict_unauthorized_probability(self, assessment: RiskAssessment) -> float: ...
