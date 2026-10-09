"""DevOps Agent — CLI-агент для генерации и диагностики инфраструктурного обвеса Python-бэкенда."""

from __future__ import annotations

__version__ = "0.1.0"


def main() -> None:
    """Точка входа консольного скрипта `devops-agent`."""
    from devops_agent.cli import app

    app()
