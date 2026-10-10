"""Общие утилиты Discovery: обход файлов с пропуском служебных каталогов."""

from __future__ import annotations

import os
import re
from pathlib import Path
from collections.abc import Iterator

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".devopsagent",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".idea",
}


def iter_files(root: Path) -> Iterator[Path]:
    """Yield все файлы репозитория, пропуская служебные каталоги."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            yield Path(dirpath) / filename


def iter_py_files(root: Path) -> Iterator[Path]:
    """Yield только .py-файлы репозитория."""
    for path in iter_files(root):
        if path.suffix == ".py":
            yield path


def extract_version(text: str) -> str | None:
    """Вернуть первую версию вида X.Y из строки (например ">=3.12" → "3.12")."""
    match = re.search(r"\b(\d+\.\d+)", text)
    return match.group(1) if match else None
