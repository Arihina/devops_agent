"""Artifact Synthesizer: StackProfile → черновик артефакта через LLM."""

from __future__ import annotations

from devops_agent.core.contracts import StackProfile
from devops_agent.generation.skeletons import (
    DockerfileSpec,
    deterministic_spec,
    render_dockerfile,
)
from devops_agent.llm import LLMGateway

_SYSTEM = """\
Ты — DevOps-инженер. Сгенерируй Dockerfile для Python-бэкенда.

Жёсткий скелет (не отступай от него):
- многостадийная сборка: builder → final;
- зависимости ставятся в /opt/venv и копируются в final-стадию;
- порядок слоёв: манифест → зависимости → исходники;
- final-стадия на том же slim-образе;
- не-root пользователь (useradd appuser; USER appuser);
- EXPOSE и CMD в конце.

Верни СТРОГО JSON-объект с полями:
{"base_image": str, "apt_packages": [str], "install_command": str, "entrypoint": str, "port": int}

Правила заполнения:
- base_image — python:<версия>-slim, версия строго из профиля;
- install_command — команда установки по пакетному менеджеру из профиля;
- apt_packages — нужные системные библиотеки (если не нужны — пустой список);
- entrypoint — полная команда запуска приложения (с --host и --port);
- port — порт из профиля.
"""


class ArtifactSynthesizer:
    """Синтез Dockerfile: LLM заполняет спецификацию, код собирает артефакт."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def synthesize_dockerfile(self, profile: StackProfile) -> str:
        hint = deterministic_spec(profile)
        user = (
            "Профиль проекта:\n"
            f"- Python: {profile.python_version or '?'}\n"
            f"- Пакетный менеджер: {profile.package_manager or '?'}\n"
            f"- Фреймворк: {profile.framework or '?'}\n"
            f"- Точка входа: {profile.entry_point or '?'}\n"
            f"- Порт: {profile.port or '?'}\n"
            f"- Внешние сервисы: {', '.join(profile.external_services) or 'нет'}\n"
            f"- Системные зависимости: {', '.join(profile.system_dependencies) or 'нет'}\n"
            "\nОпорная заготовка (проверь и уточни, особенно apt_packages и install_command):\n"
            f"{hint.model_dump_json()}"
        )
        spec = self.gateway.complete_json(DockerfileSpec, _SYSTEM, user)
        return render_dockerfile(spec)
