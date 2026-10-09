"""Конфигурация агента.

Приоритет значений: значения по умолчанию (в коде) → config.toml →
переменные окружения `DEVOPSAGENT_<SECTION>__<FIELD>` → флаги CLI
(флаги применяются поверх конфига на уровне команд).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from devops_agent.core.contracts import ArtifactType

ENV_PREFIX = "DEVOPSAGENT_"


class DiscoveryConfig(BaseModel):
    """Переопределения автоопределения стека (пусто — значит «авто»)."""

    python_version: str | None = None
    package_manager: str | None = None
    framework: str | None = None
    entry_point: str | None = None
    port: int | None = None


class ArtifactsConfig(BaseModel):
    """Какие артефакты генерировать и куда."""

    types: list[ArtifactType] = Field(default_factory=lambda: list(ArtifactType))
    dockerfile_path: str = "Dockerfile"
    dockerignore_path: str = ".dockerignore"
    compose_path: str = "docker-compose.yml"
    ci_path: str = ".github/workflows/ci.yml"
    on_conflict: Literal["compare", "skip", "overwrite"] = "compare"


class GatesConfig(BaseModel):
    """Пороги и правила гейтов."""

    size_threshold_mb: int = 500
    non_disableable: list[str] = Field(default_factory=lambda: ["security"])


class GenerationConfig(BaseModel):
    """Параметры обращения к модели."""

    model: str = "qwen2.5-coder:14b"
    final_model: str = "qwen3-coder:30b"
    max_iterations: int = 5
    token_budget: int = 100_000


class ExecutionConfig(BaseModel):
    """Таймауты сборки/запуска и среда исполнения."""

    build_timeout_s: int = 900
    run_timeout_s: int = 120
    container_runtime: Literal["docker", "podman"] = "docker"


class RedactionConfig(BaseModel):
    """Параметры Redaction Layer (раздел 6)."""

    extra_patterns: list[str] = Field(default_factory=list)
    excluded_files: list[str] = Field(default_factory=lambda: [".env", "*.pem", "id_rsa*"])
    preview: bool = True


class OutputConfig(BaseModel):
    """Формат вывода."""

    diff_format: Literal["unified", "git"] = "unified"
    report_verbosity: Literal["brief", "normal", "verbose"] = "normal"


class Config(BaseModel):
    """Корневая конфигурация."""

    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def _coerce_env(value: str) -> Any:
    """Превратить строку из окружения в bool/int/float/str."""
    stripped = value.strip()
    low = stripped.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    return stripped


def _env_to_nested(prefix: str) -> dict[str, Any]:
    """Собрать вложенный dict из переменных окружения с префиксом.

    Формат: `DEVOPSAGENT_GENERATION__MODEL` → `{"generation": {"model": ...}}`.
    Одиночные ключи без `__` игнорируются (списки задаются только в файле).
    """
    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = [p for p in key[len(prefix):].lower().split("__") if p]
        if len(parts) < 2:
            continue
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = _coerce_env(value)
    return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно наложить override поверх base."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path) -> Config:
    """Загрузить конфиг: дефолты → config.toml → окружение."""
    data: dict[str, Any] = {}
    if config_path.is_file():
        data = _deep_merge(data, tomllib.loads(config_path.read_text(encoding="utf-8")))
    data = _deep_merge(data, _env_to_nested(ENV_PREFIX))
    return Config.model_validate(data)


DEFAULT_CONFIG_TOML = """\
# Конфигурация DevOps Agent.
# Приоритет значений: дефолты (в коде) → этот файл → переменные окружения
# DEVOPSAGENT_<SECTION>__<FIELD> → флаги командной строки.

[discovery]
# Переопределения автоопределения стека. Пусто = определять автоматически.
# python_version = "3.12"
# package_manager = "poetry"
# framework = "fastapi"
# entry_point = "app.main:app"
# port = 8000

[artifacts]
# Какие типы артефактов генерировать.
types = ["dockerfile", "dockerignore", "compose", "ci_workflow"]
dockerfile_path = "Dockerfile"
dockerignore_path = ".dockerignore"
compose_path = "docker-compose.yml"
ci_path = ".github/workflows/ci.yml"
# Поведение при конфликте с существующим файлом: compare | skip | overwrite.
on_conflict = "compare"

[gates]
# Порог размера образа в мегабайтах для Size Gate.
size_threshold_mb = 500
# Правила, которые нельзя отключить.
non_disableable = ["security"]

[generation]
# Модель для итеративной починки и для финальной генерации.
model = "qwen2.5-coder:14b"
final_model = "qwen3-coder:30b"
max_iterations = 5
token_budget = 100000

[execution]
build_timeout_s = 900
run_timeout_s = 120
# Среда исполнения контейнеров: docker | podman.
container_runtime = "docker"

[redaction]
extra_patterns = []
excluded_files = [".env", "*.pem", "id_rsa*"]
# Показывать точный текст, уходящий в модель, до отправки.
preview = true

[output]
diff_format = "unified"
report_verbosity = "normal"
"""
