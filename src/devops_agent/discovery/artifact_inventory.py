"""Artifact Inventory: какие инфраструктурные файлы уже есть в репозитории."""

from __future__ import annotations

from pathlib import Path

from devops_agent.core.contracts import ArtifactType
from devops_agent.discovery.models import ArtifactRef
from devops_agent.discovery.util import iter_files

COMPOSE_NAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

CI_FILENAMES = {".gitlab-ci.yml", "bitbucket-pipelines.yml", ".travis.yml"}


class ArtifactInventory:
    """Сканирует репозиторий и сообщает, какие артефакты уже существуют."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def scan(self) -> list[ArtifactRef]:
        found: list[ArtifactRef] = []
        for path in iter_files(self.root):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            artifact_type = self._classify(rel, path.name)
            if artifact_type is not None:
                found.append(ArtifactRef(type=artifact_type, path=rel))
        return found

    @staticmethod
    def _classify(rel: str, name: str) -> ArtifactType | None:
        if name == "Dockerfile" or name.startswith("Dockerfile."):
            return ArtifactType.DOCKERFILE
        if name == ".dockerignore":
            return ArtifactType.DOCKERIGNORE
        if name in COMPOSE_NAMES:
            return ArtifactType.COMPOSE
        if name.endswith((".yml", ".yaml")):
            if rel.startswith(".github/workflows/"):
                return ArtifactType.CI_WORKFLOW
            if name in CI_FILENAMES or rel.startswith(".circleci/"):
                return ArtifactType.CI_WORKFLOW
        return None
