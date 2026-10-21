# src/reviewer.py
"""LLM-simulated human reviewer backed by a local Qwen3 model served by Ollama.

The gate calls approve() for an escalated tool call. approve() and deny() share one model
call per GateInput object, so a consultation (and its cost) is counted once.

Firewall: the reviewer is shown only the user's request, the tool results seen so far and
the proposed tool call. It never sees tool_metadata (risk labels), k_remaining, the system
prompt, the agent's own free text, the reason an earlier call was blocked, or anything about
the benchmark's injection tasks / attack setup.

The trajectory may be either the gate's raw AgentDojo message list (dicts with a `role`) or a
simple list of {"tool", "args", "output"} dicts (used by the labelled test cases).
"""
import json
import re
import string
import time
from pathlib import Path
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel
from tenacity import Retrying, stop_after_attempt, wait_exponential

from .types import GateInput, Reviewer

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "reviewer.txt"
DEFAULT_MODEL = "qwen3:14b"
DEFAULT_BASE_URL = "http://localhost:11434/v1"
BLOCKED_PREFIX = "Blocked by gate"       # text the gate puts in its blocked-call messages
USAGE_SOURCE = "ollama_openai_endpoint"
# Ollama runs locally, so there is no API charge. Set to None to record it as "unknown" instead.
LOCAL_COST_USD = 0.0

# Identifiers that would only appear in the prompt if our own code leaked ground truth.
FORBIDDEN = ["injection_task", "attack_type", "ground_truth",
             "security_result", "utility_result"]

_APPROVE = {"approve", "approved", "allow", "allowed", "yes"}
_DENY = {"deny", "denied", "reject", "rejected", "block", "blocked", "no"}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class Verdict(BaseModel):
    decision: Literal["approve", "deny"]
    reason: str
    error: bool = False


def firewall_check(prompt: str) -> list:
    """Return the forbidden identifiers found in a rendered prompt (empty list = clean)."""
    low = prompt.lower()
    return [w for w in FORBIDDEN if w in low]


def clean_model_text(text: str) -> str:
    """Remove Qwen3 <think> blocks, including an unclosed one from a cut-off reply."""
    text = _THINK_RE.sub("", text or "")
    if "<think>" in text:
        text = text.split("<think>")[0]
    return text.strip()


def parse_verdict(text: str) -> Verdict:
    """Parse a model reply into a Verdict. Raises ValueError if it can't be understood."""
    m = _JSON_RE.search(clean_model_text(text))
    if not m:
        raise ValueError("no JSON object in reply")
    data = json.loads(m.group(0))
    raw = str(data.get("decision", "")).strip().lower()
    if raw in _APPROVE:
        decision = "approve"
    elif raw in _DENY:
        decision = "deny"
    else:
        raise ValueError(f"unrecognised decision: {raw!r}")
    return Verdict(decision=decision, reason=str(data.get("reason", "")).strip())


# ---- helpers for AgentDojo message objects -----------------------------------------------
def _blocks_to_text(content) -> str:
    """AgentDojo content is a list of {"type": "text", "content": ...} blocks (or None / str)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if isinstance(b, dict):
            if b.get("type", "text") == "text" and b.get("content"):
                parts.append(str(b["content"]))
        elif b:
            parts.append(str(b))
    return "\n".join(parts)


def _call_parts(call):
    """(name, args) from a FunctionCall object or a plain dict."""
    if call is None:
        return None, {}
    if isinstance(call, dict):
        return call.get("function"), dict(call.get("args") or {})
    return getattr(call, "function", None), dict(getattr(call, "args", None) or {})


def cost_tracker_hook(tracker, cost_usd=LOCAL_COST_USD):
    """Build an `on_usage` callback that records every review in R5's CostTracker.

    Usage:  LLMReviewer(on_usage=cost_tracker_hook(tracker))
    The hook is bound to one tracker (one run_id), so build a fresh reviewer, or reassign
    `reviewer.on_usage`, for each run.
    """
    status_names = {"ok": "success"}          # CostTracker's default success label

    def hook(usage):
        extra = {"latency_s": usage.get("latency_s"), "local": usage.get("local", True)}
        if usage.get("error_type"):
            extra["error_type"] = usage["error_type"]
        status = usage.get("status", "unknown")
        tracker.record_call(
            component="reviewer",
            model=usage["model"],
            provider=usage["provider"],
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cost_usd=cost_usd,
            usage_source=usage.get("source", USAGE_SOURCE),
            status=status_names.get(status, status),
            request_id=usage.get("request_id"),
            **extra,
        )

    return hook


class LLMReviewer(Reviewer):
    def __init__(self, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL, client=None,
                 max_chars=1500, max_steps=10, max_tokens=512, no_think=True,
                 max_attempts=3, retry_wait=None, on_usage=None, on_attempt=None, max_format_repairs=1):
        self.model = model
        self.base_url = base_url
        self.client = client or OpenAI(base_url=base_url, api_key="ollama", timeout=120.0)
        self.template = string.Template(PROMPT_PATH.read_text())
        self.max_chars = max_chars          # per tool output (keeps prompts small)
        self.max_steps = max_steps          # only the most recent tool results are shown
        self.max_tokens = max_tokens
        self.no_think = no_think            # append Qwen3's /no_think switch
        if max_format_repairs not in (0, 1):
            raise ValueError("At most one format repair is permitted")
        self.max_format_repairs = max_format_repairs
        self.max_attempts = max_attempts
        self.retry_wait = retry_wait or wait_exponential(multiplier=1, min=1, max=8)
        self.on_usage = on_usage            # optional logical-consultation summary
        self.on_attempt = on_attempt        # optional per-HTTP-attempt usage callback

        self.consultations = 0              # reviews actually performed (one per GateInput)
        self.errors = 0
        self.firewall_hits = []
        self.task_fallbacks = 0             # times the request had to be read from the messages
        self.usage_callback_errors = 0
        self.last_usage = None
        self.log = []                       # one record per review, for failure analysis
        self.requests = []                  # exact wire request per HTTP attempt
        self._request_identity = {}
        self._last = None                   # (GateInput, Verdict): approve()/deny() share a call

    # ---- setup check -------------------------------------------------------------
    def check_ready(self):
        """Call once before a run: confirms Ollama is reachable and the model is pulled."""
        try:
            names = [m.id for m in self.client.models.list().data]
        except Exception as e:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.base_url}. Start it with `ollama serve`."
            ) from e
        if self.model not in names:
            raise RuntimeError(
                f"Model {self.model!r} not found in Ollama. Run `ollama pull {self.model}`. "
                f"Available: {names}")
        return True

    # ---- prompt building ---------------------------------------------------------
    def _clip(self, x):
        s = str(x)
        return s if len(s) <= self.max_chars else s[: self.max_chars] + " ...[truncated]"

    def _fmt_step(self, step: dict) -> Optional[str]:
        """One trajectory line, or None if this message is not shown to the reviewer."""
        role = step.get("role")
        if role is None:                    # simple format: {"tool", "args", "output"}
            tool = step.get("tool") or step.get("tool_name")
            if tool is None:
                return "- " + self._clip(json.dumps(step, default=str))
            args = json.dumps(step.get("args", {}), default=str)
            out = step.get("output", step.get("result", ""))
            return f"- {tool}({args}) -> <tool_output>{self._clip(out)}</tool_output>"

        if role != "tool":                  # system prompt, user text, agent free text: not shown
            return None

        name, args = _call_parts(step.get("tool_call"))
        label = f"{name}({json.dumps(args, default=str)})" if name else "an earlier action"
        text = _blocks_to_text(step.get("content"))
        err = step.get("error")
        if str(err or text).startswith(BLOCKED_PREFIX):
            # Say that it was blocked, but not why (policy, reviewer or budget).
            return f"- {label} -> [blocked, not executed]"
        out = text if text else (f"error: {err}" if err else "")
        return f"- {label} -> <tool_output>{self._clip(out)}</tool_output>"

    def _task_text(self, gi: GateInput) -> str:
        task = (gi.user_task_text or "").strip()
        if task:
            return task
        for step in gi.trajectory:           # fall back to the first user message
            if step.get("role") == "user":
                task = _blocks_to_text(step.get("content")).strip()
                if task:
                    self.task_fallbacks += 1
                    return task
        return "(the user's request is not available)"

    def render(self, gi: GateInput) -> str:
        # Deliberately NOT using gi.tool_metadata or gi.k_remaining.
        lines = [ln for ln in (self._fmt_step(s) for s in gi.trajectory) if ln]
        # Keep first executed results as well as recent steps: repeated denials
        # must not push the original supporting document out of review context.
        executed = [i for i, line in enumerate(lines) if '<tool_output>' in line and
                    any(step.get('role') == 'tool' for step in gi.trajectory)]
        anchors = executed[:min(2, max(0, self.max_steps - 1))]
        indexes = set(anchors)
        for i in range(len(lines)-1, -1, -1):
            if len(indexes) >= self.max_steps:
                break
            indexes.add(i)
        shown = [lines[i] for i in sorted(indexes)]
        omitted = len(lines) - len(shown)
        if omitted > 0:
            shown.insert(0, f"({omitted} earlier steps omitted)")
        return self.template.substitute(
            task=self._task_text(gi), tool=gi.tool_name,
            args=json.dumps(gi.args, default=str),
            trajectory="\n".join(shown) or "(none yet)")

    # ---- model call --------------------------------------------------------------
    def _empty_usage(self):
        return {"model": self.model, "provider": "ollama", "local": True,
                "input_tokens": None, "output_tokens": None, "cost_usd": None,
                "latency_s": None, "request_id": None, "source": USAGE_SOURCE,
                "status": "error"}

    def _raw_call(self, prompt: str):
        content = prompt + ("\n/no_think" if self.no_think else "")
        t0 = time.time()
        options = {"reasoning_effort": "none"} if self.no_think else {}
        request = dict(model=self.model, messages=[{"role": "user", "content": content}],
            temperature=0.0, seed=0, max_tokens=self.max_tokens,
            response_format={"type": "json_object"}, **options)
        self.requests.append(dict(self._request_identity, request=request))
        resp = self.client.chat.completions.create(**request)
        latency = time.time() - t0
        text = resp.choices[0].message.content or ""
        u = getattr(resp, "usage", None)
        usage = self._empty_usage()
        usage.update({"input_tokens": getattr(u, "prompt_tokens", None),
                      "output_tokens": getattr(u, "completion_tokens", None),
                      "latency_s": round(latency, 3),
                      "request_id": getattr(resp, "id", None), "status": "ok",
                      "finish_reason": getattr(resp.choices[0], "finish_reason", None)})
        return text, usage

    def _call(self, prompt: str, format_pass=0):
        for attempt in Retrying(stop=stop_after_attempt(self.max_attempts),
                                wait=self.retry_wait, reraise=True):
            with attempt:
                started = time.time()
                try:
                    text, usage = self._raw_call(prompt)
                except Exception as exc:
                    usage = self._empty_usage()
                    usage.update(error_type=type(exc).__name__, latency_s=time.time()-started)
                    self._emit_attempt(usage, attempt.retry_state.attempt_number)
                    raise
                usage["format_pass"] = format_pass
                self._emit_attempt(usage, attempt.retry_state.attempt_number)
                return text, usage

    def _emit_attempt(self, usage, number):
        if self.on_attempt is not None:
            try:
                self.on_attempt(dict(usage, attempt=number, record_type="api_attempt"))
            except Exception:
                self.usage_callback_errors += 1

    def _emit_usage(self, usage):
        if self.on_usage is None:
            return
        try:
            self.on_usage(dict(usage))
        except Exception:                    # cost logging must never break a run
            self.usage_callback_errors += 1

    def _verdict(self, gi: GateInput) -> Verdict:
        # approve() and deny() on the SAME GateInput share one call; a new GateInput
        # (even with identical content) is a new consultation, matching the gate's budget.
        if self._last is not None and self._last[0] is gi:
            return self._last[1]
        self._request_identity = dict(episode_id=gi.episode_id, call_id=gi.call_id)
        prompt = self.render(gi)
        self.firewall_hits += firewall_check(prompt)
        self.consultations += 1

        text, usage, v = None, self._empty_usage(), None
        format_errors = []
        for format_pass in range(self.max_format_repairs + 1):
            request = prompt
            if format_pass:
                # Same evidence and criteria. Never retry a valid denial.
                request += ('\nFormatting correction only: the previous response was invalid or truncated. '
                            'Return a short JSON object with decision approve or deny and a one-sentence reason. '
                            'Use exactly the original authorization criteria and evidence above.')
            try:
                text, usage = self._call(request, format_pass=format_pass)
            except Exception as e:
                usage['error_type'] = type(e).__name__
                break
            try:
                if usage.get('finish_reason') == 'length':
                    raise ValueError('truncated_response')
                v = parse_verdict(text)
                break
            except Exception as e:
                category = ('truncated_response' if usage.get('finish_reason') == 'length' else
                            'unclosed_thinking' if '<think>' in text and '</think>' not in text else
                            'invalid_verdict')
                format_errors.append(dict(category=category, detail=str(e),
                                          format_pass=format_pass, response_excerpt=text[:800]))
                usage['status'] = 'parse_error'
                usage['error_type'] = type(e).__name__
        if v is None:
            self.errors += 1
            v = Verdict(decision="deny", error=True,
                        reason=f"reviewer_error: {usage.get('error_type', 'unknown')}")

        self.last_usage = usage
        self._emit_usage(usage)
        self._last = (gi, v)
        self.log.append({"episode_id": gi.episode_id, "call_id": gi.call_id,
                         "request_prompt": prompt, "arguments": gi.args, "tool": gi.tool_name, "decision": v.decision, "reason": v.reason,
                         "error": v.error, "usage": usage, "format_errors": format_errors,
                         "format_repairs": max(0, len(format_errors) - int(v.error))})
        return v

    # ---- Reviewer interface ------------------------------------------------------
    def review(self, gate_input: GateInput) -> Verdict:
        """Full verdict (decision, reason, error flag). Used by evaluation scripts."""
        return self._verdict(gate_input)

    def approve(self, gate_input: GateInput) -> bool:
        return self._verdict(gate_input).decision == "approve"

    def deny(self, gate_input: GateInput) -> bool:
        return self._verdict(gate_input).decision == "deny"

    def stats(self) -> dict:
        return {"consultations": self.consultations, "errors": self.errors,
                "task_fallbacks": self.task_fallbacks,
                "usage_callback_errors": self.usage_callback_errors,
                "firewall_hits": list(self.firewall_hits)}
