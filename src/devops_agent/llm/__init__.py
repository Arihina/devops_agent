"""Слой LLM: шлюз к модели (этап 4)."""

from devops_agent.llm.gateway import Completion, LLMError, LLMGateway

__all__ = ["LLMGateway", "Completion", "LLMError"]
