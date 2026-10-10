"""Discovery: оркестрация детерминированного анализа репозитория (без LLM)."""

from __future__ import annotations

from pathlib import Path

from devops_agent.core.config import Config
from devops_agent.core.contracts import StackProfile
from devops_agent.discovery.artifact_inventory import ArtifactInventory
from devops_agent.discovery.dependency_resolver import DependencyResolver
from devops_agent.discovery.env_extractor import EnvExtractor
from devops_agent.discovery.models import DiscoveryResult
from devops_agent.discovery.service_detector import ServiceDetector
from devops_agent.discovery.stack_profiler import StackProfiler


class Discovery:
    """Единая точка входа детерминированного слоя."""

    def __init__(self, root: Path, config: Config | None = None) -> None:
        self.root = root
        self.config = config or Config()

    def run(self) -> DiscoveryResult:
        packages = DependencyResolver(self.root).resolve()
        package_names = [package.name for package in packages]

        profile = StackProfiler(self.root, package_names).profile()
        profile.system_dependencies = DependencyResolver(
            self.root).system_dependencies(packages)
        profile.external_services = ServiceDetector(
            self.root, package_names).detect()
        self._apply_overrides(profile)

        return DiscoveryResult(
            profile=profile,
            packages=packages,
            env_vars=EnvExtractor(self.root).extract(),
            artifacts=ArtifactInventory(self.root).scan(),
        )

    def _apply_overrides(self, profile: StackProfile) -> None:
        """Наложить переопределения профиля из секции `discovery` конфига."""
        d = self.config.discovery
        if d.python_version is not None:
            profile.python_version = d.python_version
        if d.package_manager is not None:
            profile.package_manager = d.package_manager
        if d.framework is not None:
            profile.framework = d.framework
        if d.entry_point is not None:
            profile.entry_point = d.entry_point
        if d.port is not None:
            profile.port = d.port
