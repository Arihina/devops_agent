"""Модели данных слоя Validation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from devops_agent.core.contracts import Finding, Gate, ValidationLevel, Verdict


class GateResult(BaseModel):
    """Результат одного гейта: вердикт, уровень, причина и findings."""

    gate: Gate
    level: ValidationLevel
    verdict: Verdict
    reason: str = ""
    findings: list[Finding] = Field(default_factory=list)


class AuditResult(BaseModel):
    """Совокупный результат аудита существующих артефактов."""

    artifacts: list[str] = Field(default_factory=list)
    gates: list[GateResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
