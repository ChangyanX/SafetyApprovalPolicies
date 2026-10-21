"""R3/R4 v0.1 wire contract. No model calls and no evaluator fields."""
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class CheckStatus(str, Enum):
    SATISFIED = 'SATISFIED'
    VIOLATED = 'VIOLATED'
    UNRESOLVED = 'UNRESOLVED'
    NOT_APPLICABLE = 'NOT_APPLICABLE'


class Evidence(StrictModel):
    evidence_id: str
    kind: Literal['instruction', 'observation', 'execution']
    source_call_id: str | None = None
    content: Any


class Check(StrictModel):
    check_id: str
    status: CheckStatus
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class AssessmentRequest(StrictModel):
    schema_version: Literal['r3-r4/0.1'] = 'r3-r4/0.1'
    episode_id: str
    call_id: str
    proposal_hash: str
    suite: str
    tool: str
    arguments: dict[str, Any]
    tool_semantics: dict[str, Any]
    task: str
    checks: list[Check]
    evidence: list[Evidence]
    question: str


class AssessmentResponse(StrictModel):
    schema_version: Literal['r3-r4/0.1'] = 'r3-r4/0.1'
    episode_id: str
    call_id: str
    proposal_hash: str
    status: Literal['ok', 'unavailable', 'error']
    checks: list[Check] = Field(default_factory=list)
    error: str | None = None


class StubAssessor:
    """Unavailable, not an implicit approval or a simulated model result."""
    def assess(self, request: AssessmentRequest) -> AssessmentResponse:
        return AssessmentResponse(episode_id=request.episode_id, call_id=request.call_id,
                                  proposal_hash=request.proposal_hash, status='unavailable',
                                  error='No model assessor configured for this policy')
