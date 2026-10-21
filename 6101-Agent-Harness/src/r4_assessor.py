"""Advisory R3/R4 v0.1 assessor. No scope grants, decisions or budget mutation."""
import hashlib
import json
from time import perf_counter
from typing import Callable

from openai import APIError, APITimeoutError

from .judge_types import JudgeTrace
from .llm_judge import JudgeConfig, LocalLLMJudge, _json, _unique_object
from .r3_contracts import AssessmentRequest, AssessmentResponse, CheckStatus


class AssessmentTrace(JudgeTrace):
    suite: str
    episode_id: str
    call_id: str
    proposal_hash: str
    schema_version: str
    status: str = "unavailable"
    error_code: str | None = None
    provider_called: bool = False


class LocalR3Assessor(LocalLLMJudge):
    """Inject into ScopeAwarePolicy(assessor=...). Model findings stay advisory.

    Only last_trace is retained. on_trace can persist per-call cost records;
    callback errors propagate (do not silently lose an audit record).
    A synchronous instance is intended for sequential calls, not shared threads.
    """
    _response_model = AssessmentResponse
    _default_prompt = "r3_assessor.txt"

    def __init__(self, config: JudgeConfig, *, client=None, prompt_path=None,
                 on_trace: Callable[[AssessmentTrace], None] | None = None):
        super().__init__(config, client=client, prompt_path=prompt_path)
        self.on_trace = on_trace
        self.last_trace: AssessmentTrace | None = None

    def assess(self, request: AssessmentRequest) -> AssessmentResponse:
        request = AssessmentRequest.model_validate(request).model_copy(deep=True)
        config = self.config
        started = perf_counter()
        identity = dict(schema_version=request.schema_version, episode_id=request.episode_id,
                        call_id=request.call_id, proposal_hash=request.proposal_hash)
        trace = AssessmentTrace(**identity, suite=request.suite, model=config.model,
            prompt_sha256=hashlib.sha256(self.system_prompt.encode()).hexdigest(),
            parameters=config.model_dump(exclude={"base_url", "model"}))

        def finish(response=None, *, status="unavailable", error=None):
            if response is None:
                response = AssessmentResponse(**identity, status=status, checks=[], error=error)
            trace.status, trace.error_code = response.status, error
            trace.latency_ms = (perf_counter() - started) * 1000
            self.last_trace = trace.model_copy(deep=True)
            if self.on_trace:
                self.on_trace(trace.model_copy(deep=True))
            return response

        evidence_ids = {e.evidence_id for e in request.evidence}
        check_ids = {c.check_id for c in request.checks}
        unresolved = {c.check_id for c in request.checks if c.status == CheckStatus.UNRESOLVED}
        if (len(evidence_ids) != len(request.evidence) or len(check_ids) != len(request.checks)
                or "" in evidence_ids or "" in check_ids
                or not all((request.episode_id, request.call_id, request.proposal_hash))):
            return finish(status="error", error="invalid_request_identity_or_ids")
        if not request.task.strip() or not evidence_ids:
            return finish(error="insufficient_context")
        if not unresolved:
            return finish(AssessmentResponse(**identity, status="ok", checks=[]))
        # Whole request only: never drop evidence, defaults, IDs or catalog semantics.
        if len(request.evidence) > config.max_history_messages:
            trace.history_truncated = True
            return finish(error="input_too_large")
        try:
            encoded = _json(request.model_dump(mode="json"))
        except (ValueError, TypeError, RecursionError):
            return finish(status="error", error="invalid_request_serialization")
        if len(encoded) + len(self.system_prompt) > config.max_input_chars:
            trace.history_truncated = True
            return finish(error="input_too_large")
        kwargs = dict(model=config.model, temperature=config.temperature,
            max_tokens=config.max_tokens, timeout=config.timeout_seconds,
            messages=[{"role": "system", "content": self.system_prompt},
                      {"role": "user", "content": encoded}])
        if config.response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        elif config.response_format == "json_schema":
            schema = AssessmentResponse.model_json_schema()
            # Provider strict schemas require even defaulted fields to be listed.
            for model in [schema, *schema.get("$defs", {}).values()]:
                if "properties" in model:
                    model["required"] = list(model["properties"])
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "r3_assessment", "strict": True,
                "schema": schema}}
        trace.provider_called = True
        try:
            completion = self.client.chat.completions.create(**kwargs)
        except (APITimeoutError, TimeoutError):
            return finish(error="provider_timeout")
        except (APIError, OSError):
            return finish(error="provider_error")
        try:
            usage = getattr(completion, "usage", None)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                count = getattr(usage, field, None)
                if type(count) is int and count >= 0:
                    setattr(trace, field, count)
            choice = completion.choices[0]
            content = choice.message.content
            if (choice.finish_reason != "stop" or getattr(choice.message, "refusal", None)
                    or not isinstance(content, str) or len(content) > 16000):
                raise ValueError("Incomplete output")
            # Reject duplicate keys/nonfinite numbers, then use JSON mode so strict
            # R3 enum fields parse correctly. Do not coerce via model_validate(dict).
            parsed = json.loads(content, object_pairs_hook=_unique_object)
            response = AssessmentResponse.model_validate_json(_json(parsed))
            if any(getattr(response, key) != value for key, value in identity.items()):
                raise ValueError("Stale response")
            if response.status != "ok":
                if response.checks or not response.error or not response.error.strip():
                    raise ValueError("Failure response contains findings or no error")
                # Model error text can echo private data. Keep a fixed diagnostic.
                response = AssessmentResponse(**identity, status=response.status, checks=[],
                    error="model_reported_" + response.status)
            elif response.error is not None:
                raise ValueError("Successful response contains error")
            seen = set()
            for check in response.checks:
                if (check.check_id not in unresolved or check.check_id in seen
                        or not check.evidence_ids or not set(check.evidence_ids) <= evidence_ids
                        or len(check.evidence_ids) != len(set(check.evidence_ids))
                        or not check.reason.strip() or len(check.reason) > 1200):
                    raise ValueError("Invalid check or evidence citation")
                seen.add(check.check_id)
        except (ValueError, TypeError, AttributeError, IndexError, RecursionError):
            return finish(status="error", error="invalid_model_output")
        # Keep external audit callbacks outside parsing/validation exception handling.
        # Audit failures must not be relabeled as invalid model output or retried.
        return finish(response, error=response.error)
