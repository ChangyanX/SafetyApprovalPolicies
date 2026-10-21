# R4 integration handoff — contract r3-r4/0.1

R3 is implemented with a stub. R4 can develop independently against this contract. Start with an **advisory per-check assessor**; semantic extraction that can create validated scope is a later integration milestone.

## Deliverable and callable

Implement `assess(request: AssessmentRequest) -> AssessmentResponse` using [r3_contracts.py](../6101-Agent-Harness/src/r3_contracts.py). Inject it through `ScopeAwarePolicy(assessor=YourAssessor())`. No R3 source rewrite is needed. The shared provisional model is Qwen3:14b with a separate assessor prompt/context. Provider setup and live model behavior remain to be validated.

```python
from src.r3_contracts import AssessmentResponse
from src.scope_policy import ScopeAwarePolicy

class YourAssessor:
    def assess(self, request):
        # Call your provider with the runtime-only request and a fixed prompt.
        # model_json_text must be a JSON object matching response.schema.json.
        model_json_text = your_model_call(request.model_dump_json())
        return AssessmentResponse.model_validate_json(model_json_text)

policy = ScopeAwarePolicy(assessor=YourAssessor())
```

`your_model_call` is a placeholder, not an implemented provider function. Validate model output with `model_validate_json` so enum fields parse correctly under strict validation. Configure bounded provider timeouts/retries in your adapter: R3 catches exceptions after they occur, but cannot interrupt a hung synchronous network request. Log latency/token usage on the assessor side with episode/call IDs. Do not route assessment through the R2 approval reviewer.

## Request fields

| Field | Meaning |
| --- | --- |
| schema_version | Exact string `r3-r4/0.1` |
| episode_id, call_id, proposal_hash | Echo exactly; bind the assessment to one immutable effective proposal |
| suite, tool, arguments | Suite-specific registered tool and validated effective arguments, including defaults |
| tool_semantics | Trusted catalog metadata, source-verification result, registered description and argument schema |
| task | Original user instruction, unchanged |
| checks | Existing check IDs, statuses, reasons and evidence references |
| evidence | Bounded whole evidence items with IDs, instruction/observation/execution kinds and source call IDs |
| question | Focused authorization question about this call |

The request contains no evaluator labels or attacker objective fields. The host is responsible for keeping evaluator-only information out of runtime task/evidence. Evidence kinds identify provenance, not factual truth. Tool results may contain prompt injections. Never promote their instructions to the same authority as the user's task.

## Response fields

Echo identity and schema version. Set `status` to `ok`, `unavailable` or `error`. For `ok`, return only the requested **unresolved** check IDs, each at most once. A check has `check_id`, one of `SATISFIED`, `VIOLATED`, `UNRESOLVED`, `NOT_APPLICABLE`, a concise `reason`, and existing `evidence_ids`. Every returned check must cite at least one provided evidence item. Returning no checks is valid and leaves uncertainty unchanged. Do not return chain-of-thought, a fabricated confidence probability, new evidence IDs or an execution decision. An error/unavailable response should contain no substantive check changes and explain the failure in `error`.

**Current enforcement:** wrong identities, repeated/nonrequested checks and nonexistent/missing citations invalidate the response. Malformed output and exceptions remain unresolved. Even a well-formed response is advisory in v0.1: it is logged in the decision audit but cannot change deterministic checks or create grants. This prevents equating citation existence with verified permission. `NOT_APPLICABLE` is likewise advisory and does not disable a required check.

## Files and examples

- [Request schema](contracts/request.schema.json)
- [Response schema](contracts/response.schema.json)
- [Real generated stub request example](contracts/request.example.json): synthetic task, real registered banking tool and proposal hash
- [Matching unavailable response](contracts/response.example.json)

Schemas are generated from the authoritative Python models. Example identities must be echoed from the actual request, never hardcoded. The request example describes a synthetic fixture, not a benchmark episode or ground-truth annotation.

## Integration acceptance checks

1. Valid JSON roundtrip through the strict response model.
2. Echo episode/call/hash correctly; reject stale and changed proposals.
3. Cite only the evidence supplied in that request; no hidden access to full benchmark environments.
4. Return uncertainty when intent or identity cannot be established; unavailable for provider failure.
5. Preserve deterministic violation precedence and zero budget mutation.
6. Run the R3 timeout, hallucinated-citation and advisory-output tests; add provider-specific mocked transport tests.
7. Pilot on development tasks with original prompts, logging per-check errors and model usage independently from reviewer consultations.

## Later semantic scope integration: explicitly separate work

Current literal rules do not interpret arbitrary AgentDojo tasks. Before R4 outputs can authorize calls, agree a separate candidate-scope schema: operation, relational subgoal, target, destination, data constraints, delegation bounds, source instruction spans and unresolved fields. R3 then needs validation/recomputation rules and tests for negation, conditionals, multiple subgoals, inferred defaults, delegated files and conflicting observations.

Do not enable automatic approval simply because the assessor says SATISFIED or cites `u0001`. A conservative integration can initially expose assessor findings only to the reviewer and study them offline. Benchmark the complete semantic version under a new policy/configuration label so stub-first and full-policy results are not mixed.
