# src/risk_based_policy.py
from .types import Decision, GateInput, GateOutput, Policy
from .tool_risk import risk_for

class RiskBasedPolicy(Policy):
    """
    根据工具风险元数据决定：
    - low → AUTO_APPROVE
    - medium → ESCALATE
    - high → ESCALATE（且强制记日志）
    - 如果 YAML 里指定了 default_decision，优先用它
    """

    def __init__(self, tool_risk_metadata: dict, suite_name: str | None = None):
        self.tool_risk_metadata = tool_risk_metadata
        self.suite_name = suite_name or getattr(tool_risk_metadata, "suite_name", None)

    def decide(self, gate_input: GateInput) -> GateOutput:
        if self.suite_name and gate_input.suite_name and self.suite_name != gate_input.suite_name:
            raise ValueError("Policy suite and GateInput suite disagree")
        suite_name = gate_input.suite_name or self.suite_name
        meta = risk_for(self.tool_risk_metadata, gate_input.tool_name, suite_name)
        risk = meta.get("risk", "medium")
        default_decision = meta.get("default_decision")

        if default_decision == "ESCALATE":
            return GateOutput(decision=Decision.ESCALATE, rationale=f"Review required: {gate_input.tool_name}")
        if default_decision == "AUTO_APPROVE":
            return GateOutput(decision=Decision.AUTO_APPROVE, rationale=f"Whitelisted: {gate_input.tool_name}")
        if default_decision == "AUTO_DENY":
            return GateOutput(decision=Decision.AUTO_DENY, rationale=f"Blacklisted: {gate_input.tool_name}")

        if risk == "low":
            return GateOutput(decision=Decision.AUTO_APPROVE, rationale=f"Low risk: {gate_input.tool_name}")
        if risk == "high":
            return GateOutput(decision=Decision.ESCALATE, rationale=f"High risk: {gate_input.tool_name}")
        return GateOutput(decision=Decision.ESCALATE, rationale=f"Medium risk: {gate_input.tool_name}")