"""Docker Execution: обёртка над CLI Docker через subprocess.

Используем CLI (а не Python SDK) ради прозрачности: BuildKit-флаги и кеш
передавать в subprocess проще, а результат читается напрямую из stdout/stderr.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class DockerExecution:
    """Тонкая обёртка над `docker` CLI."""

    def __init__(self, binary: str = "docker") -> None:
        self.binary = binary

    def available(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        return self._run(["version"], timeout_s=15).ok

    def build(self, context: Path, dockerfile: Path, tag: str, timeout_s: int) -> CommandResult:
        return self._run(
            ["build", "-f", str(dockerfile), "-t", tag, str(context)],
            timeout_s=timeout_s,
        )

    def inspect_size(self, tag: str) -> int | None:
        result = self._run(["image", "inspect", "-f", "{{.Size}}", tag], timeout_s=30)
        if not result.ok:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def run_detached(self, tag: str, name: str, port: int | None) -> str | None:
        args = ["run", "--rm", "-d", "--name", name]
        if port is not None:
            args += ["-p", f"127.0.0.1:{port}:{port}"]
        args.append(tag)
        result = self._run(args, timeout_s=60)
        return result.stdout.strip() if result.ok else None

    def inspect_state(self, container_id: str) -> str | None:
        result = self._run(
            ["inspect", "-f", "{{.State.Status}}", container_id], timeout_s=30
        )
        return result.stdout.strip() if result.ok else None

    def logs(self, container_id: str) -> str:
        result = self._run(["logs", container_id], timeout_s=30)
        return (result.stdout + result.stderr).strip()

    def stop_remove(self, container_id: str) -> None:
        self._run(["stop", container_id], timeout_s=30)
        self._run(["rm", "-f", container_id], timeout_s=30)

    def remove_image(self, tag: str) -> None:
        self._run(["rmi", "-f", tag], timeout_s=60)

    def compose_config(self, compose_path: Path, project_dir: Path) -> CommandResult:
        return self._run(
            ["compose", "-f", str(compose_path), "config", "--quiet"],
            cwd=project_dir,
            timeout_s=60,
        )

    def _run(
        self,
        args: list[str],
        timeout_s: int = 300,
        cwd: Path | None = None,
    ) -> CommandResult:
        try:
            proc = subprocess.run(
                [self.binary, *args],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(cwd) if cwd else None,
            )
            return CommandResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            return CommandResult(-1, "", "таймаут выполнения")
        except FileNotFoundError:
            return CommandResult(-1, "", f"{self.binary}: не найден")
