from typing import Protocol

from ..schemas import ModelStep


class ModelAdapter(Protocol):
    name: str

    def complete_step(self, task: dict, attempt: int) -> ModelStep:
        ...
