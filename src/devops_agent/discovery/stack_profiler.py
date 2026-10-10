"""Stack Profiler: дерево репозитория → StackProfile."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from devops_agent.core.contracts import StackProfile
from devops_agent.discovery.util import extract_version, iter_py_files

# Фреймворк → (пакет-маркер, порт по умолчанию).
FRAMEWORKS: dict[str, tuple[str, int]] = {
    "fastapi": ("fastapi", 8000),
    "django": ("django", 8000),
    "flask": ("flask", 5000),
    "starlette": ("starlette", 8000),
    "aiohttp": ("aiohttp", 8080),
    "tornado": ("tornado", 8888),
    "sanic": ("sanic", 8000),
    "litestar": ("litestar", 8000),
}

# Имена классов-приложений, присваивание которых считаем точкой входа.
APP_CLASSES = {"FastAPI", "Flask", "Starlette", "Litestar", "Sanic", "Tornado"}
APP_VAR_NAMES = {"app", "application"}


class StackProfiler:
    """Определение профиля стека по дереву репозитория и списку пакетов."""

    def __init__(self, root: Path, package_names: list[str] | None = None) -> None:
        self.root = root
        self.package_names = {p.lower() for p in (package_names or [])}

    def profile(self) -> StackProfile:
        """Собрать StackProfile.

        Поля external_services и system_dependencies заполняются другими
        компонентами Discovery (ServiceDetector и DependencyResolver).
        """
        framework = self._detect_framework()
        return StackProfile(
            python_version=self._detect_python_version(),
            package_manager=self._detect_package_manager(),
            framework=framework,
            entry_point=self._detect_entry_point(),
            port=self._detect_port(framework),
            migrations=self._detect_migrations(),
        )

    def _detect_python_version(self) -> str | None:
        marker = self.root / ".python-version"
        if marker.is_file():
            version = extract_version(marker.read_text(encoding="utf-8"))
            if version:
                return version
        pyproject = self.root / "pyproject.toml"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            requires = data.get("project", {}).get("requires-python")
            if requires:
                version = extract_version(str(requires))
                if version:
                    return version
        return None

    def _detect_package_manager(self) -> str | None:
        if (self.root / "uv.lock").exists():
            return "uv"
        if (self.root / "poetry.lock").exists():
            return "poetry"
        if (self.root / "Pipfile").exists():
            return "pipenv"

        pyproject = self.root / "pyproject.toml"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            tool = data.get("tool", {})
            if "poetry" in tool:
                return "poetry"
            if "pdm" in tool:
                return "pdm"
            build_requires = " ".join(
                data.get("build-system", {}).get("requires", [])).lower()
            for backend, manager in [
                ("poetry-core", "poetry"),
                ("pdm-backend", "pdm"),
                ("hatchling", "hatch"),
                ("flit_core", "flit"),
                ("setuptools", "setuptools"),
            ]:
                if backend in build_requires:
                    return manager

        if (self.root / "requirements.txt").is_file():
            return "pip"
        if (self.root / "setup.py").is_file() or (self.root / "setup.cfg").is_file():
            return "setuptools"
        return None

    def _detect_framework(self) -> str | None:
        for framework, (marker, _port) in FRAMEWORKS.items():
            if marker in self.package_names:
                return framework
        return None

    def _detect_entry_point(self) -> str | None:
        """Найти первый `app = <Framework>()` в исходниках и вернуть `module:app`."""
        for path in iter_py_files(self.root):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id in APP_VAR_NAMES
                        and self._is_app_call(node.value)
                    ):
                        module = ".".join(path.relative_to(
                            self.root).with_suffix("").parts)
                        return f"{module}:{target.id}"
        return None

    def _detect_port(self, framework: str | None) -> int | None:
        if framework is None:
            return None
        return FRAMEWORKS.get(framework, (None, None))[1]

    def _detect_migrations(self) -> list[str]:
        found: list[str] = []
        if (self.root / "migrations").is_dir():
            found.append("migrations/")
        if (self.root / "alembic.ini").is_file() or (self.root / "alembic").is_dir():
            found.append("alembic")
        return found

    @staticmethod
    def _is_app_call(node: object) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in APP_CLASSES
        )
