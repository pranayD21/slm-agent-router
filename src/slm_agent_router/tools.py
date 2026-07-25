from __future__ import annotations


TOOL_SCHEMAS = {
    "lookup_order": {"required": ["order_id"]},
    "calculate_total": {"required": ["amount", "tax"]},
    "format_reply": {"required": ["tone"]},
}


def validate_tool(tool_name: str | None, args: dict) -> tuple[bool, str | None]:
    if tool_name not in TOOL_SCHEMAS:
        return False, "wrong_tool"
    missing = [key for key in TOOL_SCHEMAS[tool_name]["required"] if key not in args]
    if missing:
        return False, "missing_required_tool_arg"
    return True, None
