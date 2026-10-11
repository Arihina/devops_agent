"""Гейты валидации: статические, сборочный, поведенческий."""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from devops_agent.core.config import Config
from devops_agent.core.contracts import (
    Finding,
    Gate,
    Severity,
    ValidationLevel,
    Verdict,
)
from devops_agent.redaction import MaskKind, Redactor, is_secret_key
from devops_agent.validation.docker import DockerExecution
from devops_agent.validation.docker_file import parse_dockerfile
from devops_agent.validation.models import GateResult

RUNTIME_WAIT_S = 8

# Маски, которые считаем секретами в артефакте (высокоэнтропийные строки —
# слишком шумные для Dockerfile, их пропускаем).
_SERIOUS_KINDS = {
    MaskKind.KEY_NAME,
    MaskKind.PROVIDER_KEY,
    MaskKind.PRIVATE_KEY,
    MaskKind.CONNECTION_STRING,
    MaskKind.JWT,
    MaskKind.CUSTOM,
}


def _verdict(findings: list[Finding]) -> Verdict:
    if any(f.severity == Severity.ERROR for f in findings):
        return Verdict.FAIL
    if findings:
        return Verdict.WARN
    return Verdict.PASS


def _tail(text: str, n: int = 20) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-n:]) if lines else ""


class Validator:
    """Набор гейтов, оценивающих существующие артефакты."""

    def __init__(self, root: Path, config: Config, docker: DockerExecution) -> None:
        self.root = root
        self.config = config
        self.docker = docker

    # Lint Gate (статический)

    def lint_dockerfile(self, dockerfile: Path) -> GateResult:
        rel = dockerfile.relative_to(self.root).as_posix()
        content = dockerfile.read_text(encoding="utf-8", errors="replace")
        info = parse_dockerfile(content)

        findings: list[Finding] = []
        if info.base_image is None:
            findings.append(Finding(
                rule="lint:no-from",
                severity=Severity.ERROR,
                location=rel,
                suggestion="Добавьте директиву FROM.",
            ))

        hadolint = shutil.which("hadolint")
        if hadolint:
            proc = subprocess.run(
                [hadolint, str(dockerfile)], capture_output=True, text=True, timeout=60
            )
            for line in proc.stdout.splitlines():
                if line.strip():
                    findings.append(Finding(
                        rule="lint:hadolint",
                        severity=Severity.WARNING,
                        location=rel,
                        suggestion=line.strip(),
                    ))
            reason = "hadolint"
        else:
            reason = "базовая проверка (hadolint не установлен)"

        return GateResult(
            gate=Gate.LINT,
            level=ValidationLevel.STATIC,
            verdict=_verdict(findings),
            reason=reason,
            findings=findings,
        )

    def lint_compose(self, compose_path: Path) -> GateResult:
        if not self.docker.available():
            return GateResult(
                gate=Gate.LINT, level=ValidationLevel.STATIC, verdict=Verdict.WARN,
                reason="пропущен: Docker недоступен",
            )
        result = self.docker.compose_config(compose_path, self.root)
        if result.ok:
            return GateResult(
                gate=Gate.LINT, level=ValidationLevel.STATIC, verdict=Verdict.PASS,
                reason="docker compose config: ok",
            )
        findings = [Finding(
            rule="lint:compose-config",
            severity=Severity.ERROR,
            location=compose_path.relative_to(self.root).as_posix(),
            suggestion=_tail(result.stderr),
        )]
        return GateResult(
            gate=Gate.LINT, level=ValidationLevel.STATIC, verdict=Verdict.FAIL,
            reason="docker compose config: ошибка", findings=findings,
        )

    def lint_ci(self, ci_path: Path) -> GateResult:
        rel = ci_path.relative_to(self.root).as_posix()
        actionlint = shutil.which("actionlint")
        if actionlint:
            proc = subprocess.run(
                [actionlint, str(ci_path)], capture_output=True, text=True, timeout=60
            )
            findings = [
                Finding(rule="lint:actionlint", severity=Severity.WARNING, location=rel, suggestion=line.strip())
                for line in proc.stdout.splitlines() if line.strip()
            ]
            verdict = Verdict.FAIL if proc.returncode != 0 else Verdict.PASS
            return GateResult(
                gate=Gate.LINT, level=ValidationLevel.STATIC, verdict=verdict,
                reason="actionlint", findings=findings,
            )
        text = ci_path.read_text(encoding="utf-8", errors="replace")
        findings = []
        if not text.strip():
            findings.append(Finding(
                rule="lint:empty", severity=Severity.ERROR, location=rel,
                suggestion="Файл пуст.",
            ))
        return GateResult(
            gate=Gate.LINT, level=ValidationLevel.STATIC, verdict=_verdict(findings),
            reason="базовая проверка (actionlint не установлен)", findings=findings,
        )

    # Security Gate (статический)

    def security(self, dockerfile: Path) -> GateResult:
        rel = dockerfile.relative_to(self.root).as_posix()
        content = dockerfile.read_text(encoding="utf-8", errors="replace")
        info = parse_dockerfile(content)

        findings: list[Finding] = []
        if info.runs_as_root:
            findings.append(Finding(
                rule="security:non-root",
                severity=Severity.ERROR,
                location=rel,
                suggestion="Добавьте USER с непривилегированным пользователем.",
            ))
        if info.base_tag in (None, "latest"):
            findings.append(Finding(
                rule="security:no-latest",
                severity=Severity.ERROR,
                location=rel,
                suggestion="Зафиксируйте тег базового образа (например python:3.12-slim).",
            ))
        for url in info.add_urls:
            findings.append(Finding(
                rule="security:no-add-url",
                severity=Severity.ERROR,
                location=rel,
                suggestion=f"Замените ADD {url} на COPY локального файла.",
            ))

        for key, _value in info.env_entries:
            if is_secret_key(key):
                findings.append(Finding(
                    rule="security:no-secrets",
                    severity=Severity.ERROR,
                    location=rel,
                    suggestion=f"В Dockerfile захардкожен секрет в ENV {key}.",
                ))

        masks = Redactor(self.config.redaction.extra_patterns).redact(content).masks
        for mask in masks:
            if mask.kind in _SERIOUS_KINDS:
                findings.append(Finding(
                    rule="security:no-secrets",
                    severity=Severity.ERROR,
                    location=f"{rel}:{mask.line or '?'}",
                    suggestion=f"Значение похоже на секрет ({mask.kind.value}).",
                ))

        return GateResult(
            gate=Gate.SECURITY, level=ValidationLevel.STATIC,
            verdict=_verdict(findings),
            reason=f"проверено {len(findings)} правил" if findings else "нарушений нет",
            findings=findings,
        )

    # Reproducibility Gate (статический)

    def reproducibility_dependencies(self) -> GateResult:
        findings: list[Finding] = []
        req = self.root / "requirements.txt"
        if req.is_file():
            unpinned = []
            for line in req.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith(("-", "--")):
                    continue
                if "==" not in line:
                    unpinned.append(line)
            if unpinned:
                findings.append(Finding(
                    rule="repro:pinned-deps",
                    severity=Severity.WARNING,
                    location=req.relative_to(self.root).as_posix(),
                    suggestion=f"Зафиксируйте версии через ==: {', '.join(unpinned[:5])}",
                ))
        else:
            has_lock = any(
                (self.root / name).exists()
                for name in ("uv.lock", "poetry.lock", "Pipfile.lock")
            )
            if not has_lock:
                findings.append(Finding(
                    rule="repro:lockfile",
                    severity=Severity.WARNING,
                    location=".",
                    suggestion="Добавьте lock-файл (uv.lock / poetry.lock) для воспроизводимости.",
                ))
        return GateResult(
            gate=Gate.REPRODUCIBILITY, level=ValidationLevel.STATIC,
            verdict=_verdict(findings),
            reason="версии зависимостей",
            findings=findings,
        )

    def reproducibility_compose(self, compose_path: Path) -> GateResult:
        findings: list[Finding] = []
        text = compose_path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r'^\s*image:\s*["\']?([^\s"\'#]+)', text, re.MULTILINE):
            image = match.group(1)
            base = image.split("@", 1)[0]
            if ":" not in base or base.endswith(":latest"):
                findings.append(Finding(
                    rule="repro:pinned-image",
                    severity=Severity.WARNING,
                    location=compose_path.relative_to(self.root).as_posix(),
                    suggestion=f"Зафиксируйте тег образа: {image}",
                ))
        return GateResult(
            gate=Gate.REPRODUCIBILITY, level=ValidationLevel.STATIC,
            verdict=_verdict(findings),
            reason="теги образов compose",
            findings=findings,
        )

    # Build Gate (сборочный)

    def build(self, dockerfile: Path) -> tuple[GateResult, str | None]:
        rel = dockerfile.relative_to(self.root).as_posix()
        if not self.docker.available():
            return (
                GateResult(gate=Gate.BUILD, level=ValidationLevel.BUILD,
                           verdict=Verdict.WARN, reason="пропущен: Docker недоступен"),
                None,
            )
        tag = f"devopsagent-audit:{secrets.token_hex(6)}"
        result = self.docker.build(
            self.root, dockerfile, tag, self.config.execution.build_timeout_s
        )
        if result.ok:
            return (
                GateResult(gate=Gate.BUILD, level=ValidationLevel.BUILD,
                           verdict=Verdict.PASS, reason="образ собран"),
                tag,
            )
        finding = Finding(
            rule="build:failed", severity=Severity.ERROR, location=rel,
            suggestion=_tail(result.stderr),
        )
        return (
            GateResult(gate=Gate.BUILD, level=ValidationLevel.BUILD,
                       verdict=Verdict.FAIL, reason="сборка упала", findings=[finding]),
            None,
        )

    # Size Gate

    def size(self, tag: str) -> GateResult:
        size_bytes = self.docker.inspect_size(tag)
        if size_bytes is None:
            return GateResult(
                gate=Gate.SIZE, level=ValidationLevel.BUILD, verdict=Verdict.WARN,
                reason="не удалось получить размер образа",
            )
        size_mb = size_bytes / (1024 * 1024)
        threshold = self.config.gates.size_threshold_mb
        if size_mb > threshold:
            finding = Finding(
                rule="size:over-threshold", severity=Severity.WARNING, location=tag,
                suggestion=f"Размер {size_mb:.1f} МБ превышает порог {threshold} МБ.",
            )
            return GateResult(
                gate=Gate.SIZE, level=ValidationLevel.BUILD, verdict=Verdict.WARN,
                reason=f"{size_mb:.1f} МБ (> {threshold} МБ)", findings=[finding],
            )
        return GateResult(
            gate=Gate.SIZE, level=ValidationLevel.BUILD, verdict=Verdict.PASS,
            reason=f"{size_mb:.1f} МБ",
        )

    # Runtime Gate (поведенческий) 

    def runtime(self, tag: str, port: int | None) -> GateResult:
        name = f"devopsagent-audit-{secrets.token_hex(6)}"
        container_id = self.docker.run_detached(tag, name, port)
        if container_id is None:
            return GateResult(
                gate=Gate.RUNTIME, level=ValidationLevel.BEHAVIORAL, verdict=Verdict.FAIL,
                reason="контейнер не запустился",
            )
        time.sleep(RUNTIME_WAIT_S)
        state = self.docker.inspect_state(container_id)
        if state == "running":
            reason = f"контейнер работает ({RUNTIME_WAIT_S} с)"
            verdict = Verdict.PASS
            if port is not None:
                if self._probe_port(port):
                    reason += f"; порт {port} отвечает"
                else:
                    reason += f"; порт {port} не ответил"
                    verdict = Verdict.WARN
            self.docker.stop_remove(container_id)
            return GateResult(
                gate=Gate.RUNTIME, level=ValidationLevel.BEHAVIORAL,
                verdict=verdict, reason=reason,
            )
        logs = self.docker.logs(container_id)
        self.docker.stop_remove(container_id)
        reason = f"контейнер упал на старте (state={state})"
        if logs:
            reason += "\n" + _tail(logs)
        finding = Finding(
            rule="runtime:crash", severity=Severity.ERROR, location=f"container {name}",
            suggestion="Проверьте точку входа и логи запуска.",
        )
        return GateResult(
            gate=Gate.RUNTIME, level=ValidationLevel.BEHAVIORAL,
            verdict=Verdict.FAIL, reason=reason, findings=[finding],
        )

    @staticmethod
    def _probe_port(port: int) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            return True
        except Exception:
            return False
