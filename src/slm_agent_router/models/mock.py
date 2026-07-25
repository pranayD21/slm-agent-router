from __future__ import annotations

from ..schemas import ModelStep


class MockModel:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role

    def complete_step(self, task: dict, attempt: int) -> ModelStep:
        case = task.get("case", "valid")
        if self.role == "local":
            if case == "invalid_json" and attempt == 0:
                return ModelStep("not-json", 0.7, task["tool"], {}, 20, 0.00001)
            if case == "low_confidence":
                return ModelStep("{}", 0.2, task["tool"], task["args"], 20, 0.00001)
            if case == "wrong_tool":
                return ModelStep("{}", 0.8, "wrong_tool", task["args"], 20, 0.00001)
            if case == "missing_arg":
                return ModelStep("{}", 0.8, task["tool"], {}, 20, 0.00001)
        return ModelStep("{}", 0.95, task["tool"], task["args"], 55 if self.role == "cloud" else 20, 0.001 if self.role == "cloud" else 0.00001)
