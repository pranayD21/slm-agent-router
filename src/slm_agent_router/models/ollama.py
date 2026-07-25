class OllamaModel:
    def __init__(self, name: str):
        self.name = name

    def complete_step(self, task, attempt):
        raise NotImplementedError("Ollama adapter contract is defined; network implementation is left for integration")
