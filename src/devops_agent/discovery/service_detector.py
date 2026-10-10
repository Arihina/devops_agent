"""Service Detector: внешние зависимости (БД, кеш, брокер) по пакетам и compose."""

from __future__ import annotations

import re
from pathlib import Path

from devops_agent.discovery.util import iter_files

# Python-пакет → имя внешнего сервиса.
SERVICE_PACKAGES: dict[str, str] = {
    "psycopg2": "postgres",
    "psycopg2-binary": "postgres",
    "psycopg": "postgres",
    "asyncpg": "postgres",
    "redis": "redis",
    "aioredis": "redis",
    "pymongo": "mongodb",
    "motor": "mongodb",
    "mysqlclient": "mysql",
    "pymysql": "mysql",
    "aiomysql": "mysql",
    "pika": "rabbitmq",
    "aio-pika": "rabbitmq",
    "kombu": "rabbitmq",
    "celery": "celery",
    "elasticsearch": "elasticsearch",
    "elasticsearch-dsl": "elasticsearch",
    "kafka-python": "kafka",
    "aiokafka": "kafka",
    "confluent-kafka": "kafka",
    "pymemcache": "memcached",
    "minio": "s3/minio",
}

# Фрагмент имени образа compose → имя сервиса.
IMAGE_HINTS: dict[str, str] = {
    "postgres": "postgres",
    "redis": "redis",
    "mongo": "mongodb",
    "mysql": "mysql",
    "mariadb": "mysql",
    "rabbitmq": "rabbitmq",
    "kafka": "kafka",
    "memcached": "memcached",
    "elasticsearch": "elasticsearch",
}

COMPOSE_NAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}


class ServiceDetector:
    """Определяет внешние сервисы по зависимостям и существующему compose."""

    def __init__(self, root: Path, package_names: list[str]) -> None:
        self.root = root
        self.package_names = {p.lower() for p in package_names}

    def detect(self) -> list[str]:
        services: list[str] = []
        for package in sorted(self.package_names):
            service = SERVICE_PACKAGES.get(package)
            if service and service not in services:
                services.append(service)
        for service in self._from_compose():
            if service not in services:
                services.append(service)
        return services

    def _from_compose(self) -> list[str]:
        found: list[str] = []
        for path in iter_files(self.root):
            if path.name not in COMPOSE_NAMES:
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r'^\s*image:\s*["\']?([^\s"\'#]+)', text, re.MULTILINE):
                base = match.group(1).split(":", 1)[0].split("/")[-1].lower()
                for hint, service in IMAGE_HINTS.items():
                    if hint in base and service not in found:
                        found.append(service)
        return found
