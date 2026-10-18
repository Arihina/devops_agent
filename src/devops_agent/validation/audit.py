"""Audit: оркестрация гейтов по существующим артефактам."""

from __future__ import annotations

from pathlib import Path

from devops_agent.core.config import Config
from devops_agent.core.contracts import ArtifactType
from devops_agent.discovery import Discovery
from devops_agent.discovery.artifact_inventory import ArtifactInventory
from devops_agent.validation.docker import DockerExecution
from devops_agent.validation.gates import Validator
from devops_agent.validation.models import AuditResult


def audit(
    root: Path,
    config: Config,
    skip_build: bool = False,
    verbose: bool = False,
) -> AuditResult:
    """Прогнать гейты по существующим артефактам и вернуть findings без изменений.

    `skip_build=True` оставляет только статическую валидацию (без сборки/запуска).
    `verbose=True` включает живой вывод `docker build` в терминал.
    """
    docker = DockerExecution(config.execution.container_runtime)
    artifacts = ArtifactInventory(root).scan()
    profile = Discovery(root, config).run().profile

    result = AuditResult(artifacts=[artifact.path for artifact in artifacts])
    if not artifacts:
        return result

    validator = Validator(root, config, docker, verbose=verbose)

    has_dockerfile = any(a.type == ArtifactType.DOCKERFILE for a in artifacts)
    if has_dockerfile:
        result.gates.append(validator.reproducibility_dependencies())

    for artifact in artifacts:
        path = root / artifact.path
        if artifact.type == ArtifactType.DOCKERFILE:
            result.gates.append(validator.lint_dockerfile(path))
            result.gates.append(validator.security(path))
            if skip_build:
                continue
            _build_result, tag = validator.build(path)
            result.gates.append(_build_result)
            if tag:
                try:
                    result.gates.append(validator.size(tag))
                    result.gates.append(validator.runtime(tag, profile.port))
                finally:
                    docker.remove_image(tag)
        elif artifact.type == ArtifactType.COMPOSE:
            result.gates.append(validator.lint_compose(path))
            result.gates.append(validator.reproducibility_compose(path))
        elif artifact.type == ArtifactType.CI_WORKFLOW:
            result.gates.append(validator.lint_ci(path))

    for gate_result in result.gates:
        result.findings.extend(gate_result.findings)
    return result
