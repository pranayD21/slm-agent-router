class OpenAICompatibleModel:
    def __init__(self, name: str):
        self.name = name

    def complete_step(self, task, attempt):
        raise NotImplementedError("OpenAI-compatible adapter contract is defined; tests use mock models")
