from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agronomy_agent.agent import MLXGenerator, MockGenerator


@dataclass
class AgnoModelAdapter:
    model_id: str
    mode: str = "mock"
    max_tokens: int = 360

    def generate(self, messages: list[dict[str, str]]) -> str:
        generator: Any = MockGenerator() if self.mode == "mock" else MLXGenerator(self.model_id)
        if hasattr(generator, "max_tokens"):
            generator.max_tokens = self.max_tokens
        return str(generator.generate(messages))
