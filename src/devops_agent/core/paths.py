"""Разрешение путей внутри рабочего дерева агента."""

from __future__ import annotations

from pathlib import Path

DEVOPS_DIRNAME = ".devopsagent"


def resolve_root(explicit: Path | None) -> Path:
    """Вернуть корень целевого репозитория.

    Явный `--root` имеет приоритет; иначе — текущая рабочая директория.
    """
    return (explicit or Path.cwd()).resolve()


class Paths:
    """Пути каталога `.devopsagent/` внутри целевого репозитория."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.devops = self.root / DEVOPS_DIRNAME

    @property
    def config_file(self) -> Path:
        return self.devops / "config.toml"

    @property
    def state_file(self) -> Path:
        return self.devops / "state.json"

    @property
    def signatures_dir(self) -> Path:
        return self.devops / "signatures"

    @property
    def runs_dir(self) -> Path:
        return self.devops / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id
