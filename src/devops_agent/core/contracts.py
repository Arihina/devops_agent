"""Контракты агента.

Все сущности, которыми обмениваются слои, — Pydantic-модели: это даёт
валидацию, сериализацию в JSON (state.json / report.json) и совместимость
с `instructor` для структурного вывода модели на этапе Generation.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    """Тип генерируемого инфраструктурного артефакта."""

    DOCKERFILE = "dockerfile"
    DOCKERIGNORE = "dockerignore"
    COMPOSE = "compose"
    CI_WORKFLOW = "ci_workflow"


class Gate(str, Enum):
    """Шлюз валидации."""

    LINT = "lint"
    BUILD = "build"
    RUNTIME = "runtime"
    SECURITY = "security"
    SIZE = "size"
    REPRODUCIBILITY = "reproducibility"


class ValidationLevel(str, Enum):
    """Уровень валидации — от дешёвого к дорогому."""

    STATIC = "static"
    BUILD = "build"
    BEHAVIORAL = "behavioral"


class Verdict(str, Enum):
    """Вердикт валидации."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    REJECT = "reject"


class Severity(str, Enum):
    """Серьёзность finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosisSource(str, Enum):
    """Источник диагноза: детерминированная сигнатура или модель."""

    SIGNATURE = "signature"
    MODEL = "model"


class StackProfile(BaseModel):
    """Нормализованное описание проекта (раздел 3.3)."""

    python_version: str | None = None
    package_manager: str | None = None
    framework: str | None = None
    entry_point: str | None = None
    port: int | None = None
    migrations: list[str] = Field(default_factory=list)
    external_services: list[str] = Field(default_factory=list)
    system_dependencies: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """Вердикт гейта: сработавший гейт, уровень, лог, причина."""

    verdict: Verdict
    gate: Gate
    level: ValidationLevel
    reason: str = ""
    log: str = ""


class Artifact(BaseModel):
    """Генерируемый артефакт: тип, путь, содержимое, итерации."""

    type: ArtifactType
    target_path: str
    content: str
    iteration: int = 0
    history: list[ValidationResult] = Field(default_factory=list)


class Finding(BaseModel):
    """Замечание аудита: правило, серьёзность, место, исправление."""

    rule: str
    severity: Severity
    location: str
    suggestion: str = ""


class FailureSignature(BaseModel):
    """Известный сбой: паттерн, класс причины, типовое исправление."""

    id: str
    pattern: str
    cause_class: str
    typical_fix: str


class Diagnosis(BaseModel):
    """Результат разбора сбоя: гипотеза, уверенность, дифф, источник."""

    hypothesis: str
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_diff: str = ""
    source: DiagnosisSource
