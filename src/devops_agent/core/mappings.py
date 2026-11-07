"""Mappings: справочные таблицы агента (пакет→apt, сервис→образ, фреймворк→порт).

Встроенные значения — seed в коде. Пользовательские переопределения живут в
`.devopsagent/mappings.json` и мержатся поверх встроенных (ключ к ключу, без
полного копирования: можно указать только то, что меняешь).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

MAPPINGS_FILENAME = "mappings.json"


class ServiceSpec(BaseModel):
    """Спецификация внешнего сервиса для docker-compose."""

    name: str
    image: str
    port: int
    env: dict[str, str] = Field(default_factory=dict)
    app_env: dict[str, str] = Field(default_factory=dict)


class FrameworkSpec(BaseModel):
    """Фреймворк: пакет-маркер и порт по умолчанию."""

    marker: str
    port: int


class Mappings(BaseModel):
    """Совокупные справочные таблицы."""

    apt_map: dict[str, list[str]] = Field(default_factory=dict)
    services: dict[str, ServiceSpec] = Field(default_factory=dict)
    frameworks: dict[str, FrameworkSpec] = Field(default_factory=dict)


BUILTIN_MAPPINGS = Mappings(
    apt_map={
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
    },
    services={
        "postgres": ServiceSpec(
            name="db", image="postgres:16-alpine", port=5432,
            env={"POSTGRES_DB": "app", "POSTGRES_USER": "postgres", "POSTGRES_PASSWORD": "postgres"},
            app_env={"DATABASE_URL": "postgresql://postgres:postgres@db:5432/app"},
        ),
        "redis": ServiceSpec(
            name="cache", image="redis:7-alpine", port=6379,
            app_env={"REDIS_URL": "redis://cache:6379/0"},
        ),
        "mysql": ServiceSpec(
            name="db", image="mysql:8.4", port=3306,
            env={"MYSQL_DATABASE": "app", "MYSQL_USER": "app", "MYSQL_PASSWORD": "app", "MYSQL_ROOT_PASSWORD": "root"},
            app_env={"DATABASE_URL": "mysql://app:app@db:3306/app"},
        ),
        "mongodb": ServiceSpec(
            name="db", image="mongo:7", port=27017,
            app_env={"MONGODB_URL": "mongodb://db:27017/app"},
        ),
        "rabbitmq": ServiceSpec(
            name="broker", image="rabbitmq:3-management", port=5672,
            app_env={"RABBITMQ_URL": "amqp://broker:5672/"},
        ),
        "memcached": ServiceSpec(
            name="cache", image="memcached:1-alpine", port=11211,
            app_env={"MEMCACHED_URL": "memcached://cache:11211/"},
        ),
        "elasticsearch": ServiceSpec(
            name="search", image="elasticsearch:8.13.0", port=9200,
            env={"discovery.type": "single-node"},
            app_env={"ELASTICSEARCH_URL": "http://search:9200"},
        ),
        "kafka": ServiceSpec(
            name="broker", image="bitnami/kafka:3.7", port=9092,
            app_env={"KAFKA_BOOTSTRAP_SERVERS": "broker:9092"},
        ),
    },
    frameworks={
        "fastapi": FrameworkSpec(marker="fastapi", port=8000),
        "django": FrameworkSpec(marker="django", port=8000),
        "flask": FrameworkSpec(marker="flask", port=5000),
        "starlette": FrameworkSpec(marker="starlette", port=8000),
        "aiohttp": FrameworkSpec(marker="aiohttp", port=8080),
        "tornado": FrameworkSpec(marker="tornado", port=8888),
        "sanic": FrameworkSpec(marker="sanic", port=8000),
        "litestar": FrameworkSpec(marker="litestar", port=8000),
    },
)


def mappings_path(root: Path) -> Path:
    return root / ".devopsagent" / MAPPINGS_FILENAME


def load_mappings(root: Path) -> Mappings:
    """Встроенные значения + пользовательские переопределения (пользователь побеждает)."""
    path = mappings_path(root)
    if not path.is_file():
        return BUILTIN_MAPPINGS
    try:
        user = Mappings.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — некорректный файл игнорируем, остаёмся на встроенных
        return BUILTIN_MAPPINGS
    return Mappings(
        apt_map={**BUILTIN_MAPPINGS.apt_map, **user.apt_map},
        services={**BUILTIN_MAPPINGS.services, **user.services},
        frameworks={**BUILTIN_MAPPINGS.frameworks, **user.frameworks},
    )


def load_user_mappings(root: Path) -> Mappings:
    """Загрузить только пользовательский слой mappings.json (или пустой)."""
    path = mappings_path(root)
    if not path.is_file():
        return Mappings()
    try:
        return Mappings.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return Mappings()


def save_mappings(root: Path, mappings: Mappings) -> Path:
    """Записать mappings.json (только пользовательский слой)."""
    path = mappings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mappings.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
