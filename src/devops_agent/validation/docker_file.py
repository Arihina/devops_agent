"""Минимальный парсер Dockerfile для статических гейтов.

Dockerfile линеен и не требует полноценного парсера: разбираем логические
строки (с учётом переносов `\\`) и инструкции, нужные гейтам.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class DockerfileInfo:
    """Извлечённые из Dockerfile факты, нужные гейтам."""

    base_image: str | None = None
    base_tag: str | None = None
    base_digest: str | None = None
    users: list[str] = field(default_factory=list)
    add_urls: list[str] = field(default_factory=list)
    env_entries: list[tuple[str, str]] = field(default_factory=list)

    @property
    def runs_as_root(self) -> bool:
        if not self.users:
            return True  # нет USER → по умолчанию root
        return self.users[-1] in ("root", "0")


def _logical_lines(content: str) -> list[str]:
    """Склеить строки, продолжающиеся через `\\`."""
    logical: list[str] = []
    buf = ""
    for line in content.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
        else:
            buf += stripped
            logical.append(buf)
            buf = ""
    if buf.strip():
        logical.append(buf)
    return logical


def _parse_from(args: str) -> tuple[str | None, str | None, str | None]:
    """Разобрать аргумент FROM в (образ, тег, дайджест)."""
    parts = args.split()
    ref = parts[-1] if parts else ""
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    if ":" in ref:
        image, tag = ref.rsplit(":", 1)
    else:
        image, tag = ref, None
    return image or None, tag or None, digest


def _parse_env(args: str) -> tuple[str, str]:
    if "=" in args:
        key, value = args.split("=", 1)
        return key.strip(), value.strip()
    parts = args.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return args.strip(), ""


def parse_dockerfile(content: str) -> DockerfileInfo:
    info = DockerfileInfo()
    for raw in _logical_lines(content):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z]+)\s+(.*)$", line)
        if not match:
            continue
        instruction = match.group(1).upper()
        args = match.group(2).strip()

        if instruction == "FROM" and info.base_image is None:
            info.base_image, info.base_tag, info.base_digest = _parse_from(args)
        elif instruction == "USER":
            if args.split():
                info.users.append(args.split()[0])
        elif instruction == "ADD":
            source = args.split()[0] if args.split() else ""
            if source.startswith(("http://", "https://")):
                info.add_urls.append(source)
        elif instruction == "ENV":
            key, value = _parse_env(args)
            if key:
                info.env_entries.append((key, value))
    return info
