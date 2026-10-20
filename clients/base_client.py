from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class ModelResponse:
    text: str
    model: str
    usage: dict[str, Any] | None = None
    raw_response: Any = None

class BaseClient(ABC):
    def __init__(self, model, temperature=0.0, max_tokens=5000):
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
    @abstractmethod
    def send_prompt(self, prompt: str, schema: dict | None = None) -> ModelResponse: ...
