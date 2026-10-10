"""Модели данных слоя Discovery.

Дополняют контракты из core.contracts: `DiscoveryResult` агрегирует всё, что
детерминированно извлекается из репозитория без обращения к модели.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from devops_agent.core.contracts import ArtifactType, StackProfile


class Package(BaseModel):
    """Один Python-пакет из манифеста зависимостей."""

    name: str
    spec: str | None = None  # сырой спецификатор версии, например ">=3.0"


class EnvVar(BaseModel):
    """Переменная окружения, читаемая кодом."""

    name: str
    type: str | None = None
    default: str | None = None
    locations: list[str] = Field(default_factory=list)  # "file:line"


class ArtifactRef(BaseModel):
    """Найденный в репозитории инфраструктурный файл."""

    type: ArtifactType
    path: str


class DiscoveryResult(BaseModel):
    """Совокупный результат детерминированного анализа репозитория."""

    profile: StackProfile
    packages: list[Package] = Field(default_factory=list)
    env_vars: list[EnvVar] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
