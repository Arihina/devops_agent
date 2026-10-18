"""Скелеты артефактов.

Скелет фиксирует то, что модель систематически делает плохо: многостадийная
сборка, зависимости в /opt/venv, порядок слоёв, non-root, EXPOSE/CMD в конце.
Модель заполняет только переменные части — `DockerfileSpec`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from devops_agent.core.contracts import StackProfile


class DockerfileSpec(BaseModel):
    """Переменные части Dockerfile, которые заполняет модель."""

    base_image: str
    apt_packages: list[str] = Field(default_factory=list)
    install_command: str
    entrypoint: str
    port: int = 8000


def base_image_for(python_version: str | None) -> str:
    return f"python:{python_version or '3.12'}-slim"


def install_command_for(package_manager: str | None) -> str:
    if package_manager == "poetry":
        return "pip install --no-cache-dir poetry && poetry install --no-dev"
    if package_manager == "pipenv":
        return "pip install --no-cache-dir pipenv && pipenv install --deploy --system"
    return "pip install --no-cache-dir -r requirements.txt"


def entrypoint_for(profile: StackProfile) -> str:
    port = profile.port or 8000
    entry = profile.entry_point or ""
    framework = (profile.framework or "").lower()
    if framework == "django":
        return f"python manage.py runserver 0.0.0.0:{port}"
    if framework == "flask":
        if entry:
            return f"gunicorn {entry} -b 0.0.0.0:{port}"
        return f"flask run --host 0.0.0.0 --port {port}"
    if entry and ":" in entry:
        return f"uvicorn {entry} --host 0.0.0.0 --port {port}"
    if entry:
        return f"python {entry}"
    return f"python -m http.server {port}"


def deterministic_spec(profile: StackProfile) -> DockerfileSpec:
    """Детерминированная заготовка спецификации (без модели).

    Используется как опора для промпта и как fallback, если модель недоступна.
    """
    return DockerfileSpec(
        base_image=base_image_for(profile.python_version),
        apt_packages=list(profile.system_dependencies),
        install_command=install_command_for(profile.package_manager),
        entrypoint=entrypoint_for(profile),
        port=profile.port or 8000,
    )


def render_dockerfile(spec: DockerfileSpec) -> str:
    """Собрать Dockerfile из фиксированного скелета и спецификации."""
    apt = " ".join(spec.apt_packages)
    apt_line = (
        f"RUN apt-get update && apt-get install -y --no-install-recommends {apt} "
        "&& rm -rf /var/lib/apt/lists/*"
        if apt
        else ""
    )

    lines: list[str] = [
        f"FROM {spec.base_image} AS builder",
        "",
        "WORKDIR /app",
        "",
    ]
    if apt_line:
        lines += [apt_line, ""]
    lines += [
        "RUN python -m venv /opt/venv",
        'ENV PATH="/opt/venv/bin:$PATH"',
        "",
        "COPY requirements.txt .",
        f"RUN {spec.install_command}",
        "",
        "COPY . .",
        "",
        f"FROM {spec.base_image}",
        "",
    ]
    if apt_line:
        lines += [apt_line, ""]
    lines += [
        "COPY --from=builder /opt/venv /opt/venv",
        'ENV PATH="/opt/venv/bin:$PATH"',
        "",
        "WORKDIR /app",
        "COPY . .",
        "",
        "RUN useradd --create-home appuser",
        "USER appuser",
        "",
        f"EXPOSE {spec.port}",
        "",
        f"CMD {spec.entrypoint}",
        "",
    ]
    return "\n".join(lines)
