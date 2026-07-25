from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ModelStep:
    text: str
    confidence: float
    tool_name: str | None
    tool_args: dict
    latency_ms: int
    cost_usd: float


def parse_policy(path: str) -> dict:
    data = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            value = value.strip('"')
            if value.lower() in {"true", "false"}:
                data[key] = value.lower() == "true"
            else:
                try:
                    data[key] = float(value) if "." in value else int(value)
                except ValueError:
                    data[key] = value
    return data


def load_tasks(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
