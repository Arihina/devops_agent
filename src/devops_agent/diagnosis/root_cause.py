"""Root Cause Analyst: нераспознанные сбои → гипотеза через LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devops_agent.core.contracts import Diagnosis, DiagnosisSource
from devops_agent.llm import LLMGateway


class RootCauseOutput(BaseModel):
    """Структурный ответ модели."""

    hypothesis: str
    confidence: float = Field(ge=0.0, le=1.0)
    fix: str = ""


_SYSTEM = """\
Ты — DevOps-инженер. Разбери ошибку сборки/CI по логу.
Верни СТРОГО JSON-объект с полями:
{"hypothesis": "наиболее вероятная корневая причина", "confidence": 0.0..1.0, "fix": "конкретное исправление"}
confidence — честная уверенность в гипотезе; если не уверен, ставь низкое значение.
"""


class RootCauseAnalyst:
    """Гипотеза о причине для логов, не покрытых сигнатурами."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def analyze(self, log_text: str) -> Diagnosis:
        output = self.gateway.complete_json(RootCauseOutput, _SYSTEM, log_text)
        return Diagnosis(
            hypothesis=output.hypothesis,
            confidence=output.confidence,
            proposed_diff=output.fix,
            source=DiagnosisSource.MODEL,
        )
