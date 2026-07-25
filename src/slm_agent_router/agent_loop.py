from __future__ import annotations

import json
from pathlib import Path

from .metrics import summarize
from .router import escalation_reasons


def run_tasks(tasks: list[dict], policy: dict, local_model, cloud_model, output: str | Path) -> dict:
    rows = []
    max_retries = int(policy.get("max_local_retries", 1))
    for task in tasks:
        local_retries = 0
        escalated = False
        reasons = []
        step = local_model.complete_step(task, 0)
        reasons = escalation_reasons(step, policy)
        while reasons and local_retries < max_retries and "low_confidence" not in reasons:
            local_retries += 1
            step = local_model.complete_step(task, local_retries)
            reasons = escalation_reasons(step, policy)
        if reasons:
            escalated = True
            step = cloud_model.complete_step(task, 0)
            cloud_reasons = escalation_reasons(step, policy)
            reasons = reasons + [f"cloud_{r}" for r in cloud_reasons]
        success = not escalation_reasons(step, policy)
        rows.append({
            "task_id": task["task_id"],
            "success": success,
            "handled_locally": success and not escalated,
            "escalated": escalated,
            "escalation_reasons": reasons,
            "local_retries": local_retries,
            "cost_usd": step.cost_usd,
            "latency_ms": step.latency_ms,
        })
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    return {"rows": rows, "metrics": summarize(rows)}
