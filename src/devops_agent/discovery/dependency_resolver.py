"""Dependency Resolver: манифест зависимостей → пакеты и apt-зависимости"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from devops_agent.discovery.models import Package

# Справочник известных соответствий «Python-пакет → apt-пакет».
APT_MAP: dict[str, list[str]] = {
    "psycopg2": ["libpq-dev"],
    "psycopg": ["libpq-dev"],
    "asyncpg": ["libpq-dev"],
    "mysqlclient": ["default-libmysqlclient-dev"],
    "lxml": ["libxml2-dev", "libxslt1-dev"],
    "pillow": ["libjpeg-dev", "zlib1g-dev", "libpng-dev"],
    "pycurl": ["libcurl4-openssl-dev"],
    "cryptography": ["libssl-dev"],
    "h5py": ["libhdf5-dev"],
    "weasyprint": ["libpango-1.0-0", "libcairo2"],
    "pyodbc": ["unixodbc-dev"],
    "gdal": ["libgdal-dev"],
    "rasterio": ["libgdal-dev"],
}


def _normalize(name: str) -> str:
    """Нормализовать имя пакета: регистр и разделители к каноническому виду."""
    return re.sub(r"[-_.]+", "-", name).lower()


class DependencyResolver:
    """Сбор Python-пакетов из pyproject.toml / requirements.txt."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resolve(self) -> list[Package]:
        """Вернуть объединённый список пакетов из всех поддерживаемых манифестов."""
        packages: dict[str, Package] = {}
        for pkg in [*self._from_pyproject(), *self._from_requirements()]:
            packages.setdefault(_normalize(pkg.name), pkg)
        return sorted(packages.values(), key=lambda p: p.name.lower())

    def system_dependencies(self, packages: list[Package]) -> list[str]:
        """Вернуть apt-пакеты, требуемые Python-пакетами, по справочнику."""
        apt: list[str] = []
        for pkg in packages:
            for apt_pkg in APT_MAP.get(_normalize(pkg.name), []):
                if apt_pkg not in apt:
                    apt.append(apt_pkg)
        return apt

    def _from_pyproject(self) -> list[Package]:
        manifest = self.root / "pyproject.toml"
        if not manifest.is_file():
            return []
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        result: list[Package] = []

        # PEP 621: [project].dependencies
        for dep in data.get("project", {}).get("dependencies", []):
            if isinstance(dep, str):
                result.append(self._parse_requirement(dep))

        # Poetry: [tool.poetry].dependencies
        poetry_deps = data.get("tool", {}).get(
            "poetry", {}).get("dependencies", {})
        for name, spec in poetry_deps.items():
            if name.lower() == "python":
                continue
            result.append(Package(name=name, spec=self._spec_to_str(spec)))
        return result

    def _from_requirements(self) -> list[Package]:
        manifest = self.root / "requirements.txt"
        if not manifest.is_file():
            return []
        result: list[Package] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "--")):
                continue
            result.append(self._parse_requirement(line))
        return result

    @staticmethod
    def _parse_requirement(req: str) -> Package:
        """Разобрать строку вида "fastapi>=0.115" на имя и спецификатор."""
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*(.*)$", req)
        if not match:
            return Package(name=req.strip(), spec=None)
        spec = match.group(2).strip() or None
        return Package(name=match.group(1), spec=spec)

    @staticmethod
    def _spec_to_str(spec: object) -> str | None:
        if isinstance(spec, str):
            return spec
        if isinstance(spec, dict):
            version = spec.get("version")
            return str(version) if version else None
        return None
