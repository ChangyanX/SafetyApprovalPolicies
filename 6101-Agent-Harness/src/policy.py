# src/policies.py
from .types import Decision, GateInput, GateOutput, Policy


class FullApprovePolicy(Policy):
    """Baseline: approve every tool call, never consult the reviewer."""

    name = "full_approve"

    def decide(self, gate_input: GateInput) -> GateOutput:
        return GateOutput(
            decision=Decision.AUTO_APPROVE,
            rationale=f"Full-approve baseline: {gate_input.tool_name}",
        )


class FullEscalatePolicy(Policy):
    """Baseline: escalate every tool call to the reviewer.

    When the budget is exhausted the gate (not this class) turns ESCALATE into a deny.
    """

    name = "full_escalate"

    def decide(self, gate_input: GateInput) -> GateOutput:
        return GateOutput(
            decision=Decision.ESCALATE,
            rationale=f"Full-escalate baseline: {gate_input.tool_name}",
        )


# Policies that need no configuration.
POLICIES = {
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
}

POLICY_LABELS = ("full_approve", "full_escalate", "risk_based")


def make_policy(label: str, tool_risk_metadata=None, suite_name=None) -> Policy:
    """Build a policy from the label used in the experiment manifest.

    "risk_based" needs the loaded tool risk metadata (see src/tool_risk.py).
    """
    if label in POLICIES:
        return POLICIES[label]()
    if label == "risk_based":
        if tool_risk_metadata is None:
            raise ValueError("risk_based policy needs tool_risk_metadata")
        from .risk_based_policy import RiskBasedPolicy
        return RiskBasedPolicy(tool_risk_metadata, suite_name=suite_name)
    raise ValueError(f"unknown policy label {label!r}; expected one of {POLICY_LABELS}")
