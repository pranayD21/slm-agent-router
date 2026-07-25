def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    escalated = sum(row["escalated"] for row in rows)
    local = sum(row["handled_locally"] for row in rows)
    return {
        "tasks": total,
        "success_rate": round(sum(row["success"] for row in rows) / total, 4) if total else 0,
        "percent_steps_handled_locally": round(local / total, 4) if total else 0,
        "escalation_rate": round(escalated / total, 4) if total else 0,
        "local_retries": sum(row["local_retries"] for row in rows),
        "estimated_cost_usd": round(sum(row["cost_usd"] for row in rows), 6),
        "latency_ms": sum(row["latency_ms"] for row in rows),
    }
