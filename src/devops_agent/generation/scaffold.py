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


def _write_draft(content: str) -> Path:
    fd, name = tempfile.mkstemp(prefix="devopsagent-draft-", suffix=".Dockerfile")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return Path(name)


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
