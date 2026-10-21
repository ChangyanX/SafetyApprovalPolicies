"""Bounded, synchronous local OpenAI-compatible risk assessor."""
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Literal

from openai import APIError, APITimeoutError, OpenAI
from pydantic import Field, ValidationError

from .judge_types import JudgeInput, JudgeResult, JudgeTrace, RiskAssessment, StrictModel
from .types import GateInput


class JudgeConfig(StrictModel):
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    timeout_seconds: float = Field(default=30.0, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=512, gt=0)
    max_input_chars: int = Field(default=24000, ge=1000)
    max_history_messages: int = Field(default=512, ge=0)
    response_format: Literal["json_object", "json_schema", "none"] = "json_object"
    no_think: bool = False

    @classmethod
    def from_env(cls) -> "JudgeConfig":
        # No implicit cloud endpoint or model fallback.
        return cls(model=os.environ["JUDGE_MODEL"], base_url=os.environ["JUDGE_BASE_URL"])


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class LocalLLMJudge:
    _response_model = RiskAssessment
    _default_prompt = "risk_judge.txt"

    def __init__(self, config: JudgeConfig, *, client=None, prompt_path: str | Path | None = None):
        self.config = config
        self.client = client if client is not None else OpenAI(
            base_url=config.base_url, api_key=os.environ.get("JUDGE_API_KEY", "local"),
            timeout=config.timeout_seconds, max_retries=0,
        )
        path = Path(prompt_path) if prompt_path else Path(__file__).parent / "prompts" / self._default_prompt
        self.system_prompt = path.read_text(encoding="utf-8") + "\nJSON schema:\n" + _json(self._response_model.model_json_schema())

    def assess(self, value: JudgeInput | GateInput) -> JudgeResult:
        value = JudgeInput.from_gate(value) if isinstance(value, GateInput) else value
        config = self.config
        trace = JudgeTrace(
            model=config.model,
            prompt_sha256=hashlib.sha256(self.system_prompt.encode()).hexdigest(),
            parameters=config.model_dump(exclude={"base_url", "model"}),
        )
        started = perf_counter()

        def result(status, assessment=None):
            trace.latency_ms = (perf_counter() - started) * 1000
            return JudgeResult(status=status, schema_valid=assessment is not None, trace=trace, assessment=assessment or RiskAssessment(
                authorization="uncertain", operational_risk="unknown", risk_score=1.0,
                confidence=0.0, injection_suspected=False, context_sufficient=False,
                rationale="Assessment unavailable; do not interpret this result as safe.",
            ))

        if not value.user_task_text.strip():
            return result("insufficient_context")
        if len(value.trajectory) > config.max_history_messages:
            trace.history_truncated = True
            return result("insufficient_context")
        payload = {
            "trusted_user_request": value.user_task_text,
            "trusted_authorization_scope": value.authorization_scope,
            "proposed_call": {"tool_name": value.tool_name, "args": value.args},
            "tool_metadata": value.tool_metadata,
            "untrusted_trajectory": value.trajectory,
            "history_truncated": False,
        }
        try:
            encoded = _json(payload)
            if len(self.system_prompt) + len(encoded) > config.max_input_chars:
                trace.history_truncated = bool(value.trajectory)
                return result("insufficient_context")
        except (ValueError, TypeError, RecursionError):
            return result("insufficient_context")
        kwargs = dict(model=config.model, temperature=config.temperature,
                      max_tokens=config.max_tokens, timeout=config.timeout_seconds,
                      messages=[{"role": "system", "content": self.system_prompt},
                                {"role": "user", "content": encoded}])
        if config.no_think:
            kwargs.update(reasoning_effort="none", extra_body={"think": False})
        if config.response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        elif config.response_format == "json_schema":
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "risk_assessment", "strict": True, "schema": RiskAssessment.model_json_schema()}}
        try:
            response = self.client.chat.completions.create(**kwargs)
        except (APITimeoutError, TimeoutError):
            return result("timeout")
        except (APIError, OSError):
            # Do not persist exception strings: servers may echo sensitive inputs.
            return result("service_error")
        try:
            if response.usage:
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    setattr(trace, field, getattr(response.usage, field, None))
            choice = response.choices[0]
            if choice.finish_reason != "stop" or getattr(choice.message, "refusal", None):
                return result("invalid_output")
            content = choice.message.content
            if not isinstance(content, str) or len(content) > 16000:
                return result("invalid_output")
            parsed = json.loads(content, object_pairs_hook=_unique_object)
            assessment = RiskAssessment.model_validate(parsed)
        except (ValueError, TypeError, IndexError, AttributeError, RecursionError, ValidationError):
            return result("invalid_output")
        if (not assessment.context_sufficient or assessment.authorization == "uncertain"
                or assessment.operational_risk == "unknown"):
            return result("insufficient_context", assessment)
        return result("ok", assessment)
