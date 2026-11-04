"""Scaffold: сценарий генерации артефактов с петлёй починки.

Dockerfile: синтез → Build Gate → Repair Synthesizer (до N итераций) →
Security Gate (отклонение без починки) → приём/отклонение.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel

from devops_agent.core.config import Config
from devops_agent.core.contracts import StackProfile, Verdict
from devops_agent.generation.repair import RepairSynthesizer
from devops_agent.generation.skeletons import render_compose, render_ci
from devops_agent.generation.synthesizer import ArtifactSynthesizer
from devops_agent.llm import LLMGateway
from devops_agent.validation.docker import DockerExecution
from devops_agent.validation.gates import Validator


class ScaffoldResult(BaseModel):
    """Итог сценария scaffold."""

    accepted: bool
    content: str = ""
    iterations: int = 0
    reason: str = ""


def _write_draft(content: str, suffix: str = ".Dockerfile") -> Path:
    fd, name = tempfile.mkstemp(prefix="devopsagent-draft-", suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return Path(name)


def _tail(text: str, n: int = 20) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-n:]) if lines else ""


def scaffold_docker(
    root: Path,
    config: Config,
    profile: StackProfile,
    verbose: bool = False,
) -> ScaffoldResult:
    gateway = LLMGateway(model=config.generation.model)
    synthesizer = ArtifactSynthesizer(gateway)
    repair = RepairSynthesizer(gateway)
    docker = DockerExecution(config.execution.container_runtime)
    validator = Validator(root, config, docker, verbose=verbose)

    content = synthesizer.synthesize_dockerfile(profile)

    for iteration in range(1, config.generation.max_iterations + 1):
        draft_path = _write_draft(content)
        try:
            build_result, tag = validator.build(draft_path)
            if tag:
                docker.remove_image(tag)
        finally:
            draft_path.unlink(missing_ok=True)

        if build_result.verdict == Verdict.PASS:
            sec_path = _write_draft(content)
            try:
                security = validator.security(sec_path)
            finally:
                sec_path.unlink(missing_ok=True)
            if security.verdict == Verdict.FAIL:
                return ScaffoldResult(
                    accepted=False,
                    content=content,
                    iterations=iteration,
                    reason=f"Security Gate не пройден: {security.reason}",
                )
            return ScaffoldResult(
                accepted=True,
                content=content,
                iterations=iteration,
                reason="Build Gate пройден",
            )

        error_log = ""
        if build_result.findings:
            error_log = build_result.findings[0].suggestion
        else:
            error_log = build_result.reason

        content = repair.repair_dockerfile(content, error_log)

    return ScaffoldResult(
        accepted=False,
        content=content,
        iterations=config.generation.max_iterations,
        reason="лимит итераций починки исчерпан",
    )


def _lint_result(validator: Validator, content: str, suffix: str, lint) -> ScaffoldResult:
    """Прогнать lint-гейт по черновику и вернуть ScaffoldResult."""
    draft = _write_draft(content, suffix=suffix)
    try:
        gate = lint(draft)
    finally:
        draft.unlink(missing_ok=True)
    if gate.verdict == Verdict.FAIL:
        return ScaffoldResult(
            accepted=False, content=content, reason=f"Lint Gate: {gate.reason}"
        )
    return ScaffoldResult(accepted=True, content=content, iterations=1, reason=gate.reason)


def scaffold_compose(
    root: Path,
    config: Config,
    profile: StackProfile,
    verbose: bool = False,
) -> ScaffoldResult:
    """Сгенерировать docker-compose и проверить `docker compose config`."""
    validator = Validator(
        root, config, DockerExecution(config.execution.container_runtime), verbose=verbose
    )
    return _lint_result(validator, render_compose(profile), ".yml", validator.lint_compose)


def scaffold_ci(
    root: Path,
    config: Config,
    profile: StackProfile,
    verbose: bool = False,
) -> ScaffoldResult:
    """Сгенерировать CI-workflow (без запуска на живом GitHub)."""
    validator = Validator(
        root, config, DockerExecution(config.execution.container_runtime), verbose=verbose
    )
    return _lint_result(validator, render_ci(profile), ".yml", validator.lint_ci)
