"""Env Extractor: извлечение переменных окружения из исходников через AST."""

from __future__ import annotations

import ast
from pathlib import Path

from devops_agent.discovery.models import EnvVar
from devops_agent.discovery.util import iter_py_files


class EnvExtractor:
    """Находит чтение переменных окружения и выводит имя, тип и значение по умолчанию.

    Распознаёт `os.getenv("X")`, `os.getenv("X", "d")`, `os.environ.get("X")`,
    `os.environ["X"]`. Прямые импорты (`from os import getenv`) на этом этапе
    не обрабатываются — известное упрощение.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def extract(self) -> list[EnvVar]:
        merged: dict[str, EnvVar] = {}
        for path in iter_py_files(self.root):
            rel = path.relative_to(self.root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                hit = self._match(node)
                if hit is None:
                    continue
                name, default, dtype = hit
                location = f"{rel}:{node.lineno}"
                existing = merged.get(name)
                if existing is None:
                    merged[name] = EnvVar(
                        name=name, type=dtype, default=default, locations=[location])
                else:
                    existing.locations.append(location)
                    if existing.default is None and default is not None:
                        existing.default = default
                        existing.type = dtype
        return sorted(merged.values(), key=lambda v: v.name)

    def _match(self, node: ast.AST) -> tuple[str, str | None, str | None] | None:
        """Вернуть (имя, значение_по_умолчанию, тип) или None."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "getenv" and self._is_os(node.func.value):
                return self._call_args(node)
            if node.func.attr == "get" and self._is_environ(node.func.value):
                return self._call_args(node)
        if isinstance(node, ast.Subscript) and self._is_environ(node.value):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                return node.slice.value, None, None
        return None

    def _call_args(self, node: ast.Call) -> tuple[str, str | None, str | None] | None:
        if (
            not node.args
            or not isinstance(node.args[0], ast.Constant)
            or not isinstance(node.args[0].value, str)
        ):
            return None
        name = node.args[0].value
        if len(node.args) > 1:
            default, dtype = self._literal(node.args[1])
            return name, default, dtype
        return name, None, None

    @staticmethod
    def _literal(node: ast.AST) -> tuple[str | None, str | None]:
        """Вернуть (строковое представление литерала, имя Python-типа)."""
        if isinstance(node, ast.Constant):
            if node.value is None:
                return None, None
            return str(node.value), type(node.value).__name__
        return None, None

    @staticmethod
    def _is_os(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id == "os"

    def _is_environ(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "environ" and self._is_os(node.value)
