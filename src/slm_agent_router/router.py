from __future__ import annotations

from .tools import validate_tool


def escalation_reasons(step, policy: dict) -> list[str]:
    reasons = []
    if step.confidence < float(policy.get("confidence_threshold", 0.6)):
        reasons.append("low_confidence")
    ok, reason = validate_tool(step.tool_name, step.tool_args)
    if not ok:
        reasons.append(reason)
    if step.text.strip() and step.text.strip()[0] not in "{[":
        reasons.append("schema_validation_failure")
    return reasons
