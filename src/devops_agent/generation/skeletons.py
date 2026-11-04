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


# Compose и CI (детерминированные шаблоны, без LLM)

# Внешний сервис → спецификация для docker-compose.
SERVICE_SPECS: dict[str, dict] = {
    "postgres": {
        "name": "db",
        "image": "postgres:16-alpine",
        "port": 5432,
        "env": {"POSTGRES_DB": "app", "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "postgres"},
        "app_env": {"DATABASE_URL": "postgresql://postgres:postgres@db:5432/app"},
    },
    "redis": {
        "name": "cache",
        "image": "redis:7-alpine",
        "port": 6379,
        "env": {},
        "app_env": {"REDIS_URL": "redis://cache:6379/0"},
    },
    "mysql": {
        "name": "db",
        "image": "mysql:8.4",
        "port": 3306,
        "env": {"MYSQL_DATABASE": "app", "MYSQL_USER": "app", "MYSQL_PASSWORD": "app", "MYSQL_ROOT_PASSWORD": "root"},
        "app_env": {"DATABASE_URL": "mysql://app:app@db:3306/app"},
    },
    "mongodb": {
        "name": "db",
        "image": "mongo:7",
        "port": 27017,
        "env": {},
        "app_env": {"MONGODB_URL": "mongodb://db:27017/app"},
    },
    "rabbitmq": {
        "name": "broker",
        "image": "rabbitmq:3-management",
        "port": 5672,
        "env": {},
        "app_env": {"RABBITMQ_URL": "amqp://broker:5672/"},
    },
    "memcached": {
        "name": "cache",
        "image": "memcached:1-alpine",
        "port": 11211,
        "env": {},
        "app_env": {"MEMCACHED_URL": "memcached://cache:11211/"},
    },
    "elasticsearch": {
        "name": "search",
        "image": "elasticsearch:8.13.0",
        "port": 9200,
        "env": {"discovery.type": "single-node"},
        "app_env": {"ELASTICSEARCH_URL": "http://search:9200"},
    },
    "kafka": {
        "name": "broker",
        "image": "bitnami/kafka:3.7",
        "port": 9092,
        "env": {},
        "app_env": {"KAFKA_BOOTSTRAP_SERVERS": "broker:9092"},
    },
}


def render_compose(profile: StackProfile) -> str:
    """Собрать docker-compose для локальной разработки (детерминированно)."""
    services = [s for s in profile.external_services if s in SERVICE_SPECS]
    port = profile.port or 8000

    app_env: dict[str, str] = {"PORT": str(port)}
    for service in services:
        app_env.update(SERVICE_SPECS[service]["app_env"])

    lines = ["services:", "", "  app:", "    build: .", "    ports:"]
    lines.append(f'      - "{port}:{port}"')
    lines.append("    environment:")
    for key, value in app_env.items():
        lines.append(f'      {key}: "{value}"')
    if services:
        lines.append("    depends_on:")
        for service in services:
            lines.append(f"      - {SERVICE_SPECS[service]['name']}")
    lines.append("")

    for service in services:
        spec = SERVICE_SPECS[service]
        lines.append(f"  {spec['name']}:")
        lines.append(f"    image: {spec['image']}")
        if spec.get("env"):
            lines.append("    environment:")
            for key, value in spec["env"].items():
                lines.append(f'      {key}: "{value}"')
        lines.append("    ports:")
        lines.append(f'      - "{spec["port"]}:{spec["port"]}"')
        lines.append("")
    return "\n".join(lines)


def render_ci(profile: StackProfile) -> str:
    """Собрать CI-workflow (GitHub Actions, детерминированно)."""
    python_version = profile.python_version or "3.12"
    install = install_command_for(profile.package_manager)
    lines = [
        "name: CI",
        "",
        "on:",
        "  push:",
        "    branches: [main, master]",
        "  pull_request:",
        "",
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5",
        "        with:",
        f"          python-version: '{python_version}'",
        "      - name: Install dependencies",
        f"        run: {install}",
        "      - name: Run tests",
        "        run: pytest",
        "      - name: Build image",
        "        run: docker build -t app .",
        "",
    ]
    return "\n".join(lines)
