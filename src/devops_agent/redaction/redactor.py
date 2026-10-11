"""Redaction Layer.

Маскирует секреты перед отправкой текста в модель, сохраняя структуру:
имена ключей остаются, значения заменяются плейсхолдером <REDACTED>.
Полностью надёжного маскирования не существует — поэтому слой дополняется
предпросмотром (команда `redact`) и списком исключаемых файлов в конфиге.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

REDACTED = "<REDACTED>"

ENTROPY_MIN_LENGTH = 32
ENTROPY_THRESHOLD = 4.0

# Подстроки в имени ключа, по которым значение считается секретом.
SECRET_KEY_TERMS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "auth_token",
    "refresh_token",
    "session_key",
)

# Ключи известных провайдеров — по префиксам.
PROVIDER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_session_token", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("stripe_key", re.compile(
        r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
]

# scheme://user:password@host → маскируем только пароль, структура сохраняется.
URL_CREDS_RE = re.compile(
    r"(?P<prefix>://[^/\s:@]+:)(?P<secret>[^@\s/]+)(?P<suffix>@)")

# JWT: header.payload.signature.
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")

# PEM-блоки приватных ключей (многострочные).
PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)

ENV_KV_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")
YAML_KV_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*:\s+(?P<value>.*)$")
JSON_KV_RE = re.compile(r'"(?P<key>[^"]+)"\s*:\s*"(?P<value>[^"]*)"')

# Кандидаты в высокоэнтропийные токены.
TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


class MaskKind(str, Enum):
    """Класс причины маскирования."""

    KEY_NAME = "key_name"
    CONNECTION_STRING = "connection_string"
    JWT = "jwt"
    PRIVATE_KEY = "private_key"
    PROVIDER_KEY = "provider_key"
    HIGH_ENTROPY = "high_entropy"
    CUSTOM = "custom"


class MaskInfo(BaseModel):
    """Сведения об одном замаскированном фрагменте (без самого секрета)."""

    kind: MaskKind
    key: str = ""
    line: int | None = None


class RedactionResult(BaseModel):
    """Результат маскирования: итоговый текст и список масок."""

    masked_text: str
    masks: list[MaskInfo] = Field(default_factory=list)


def shannon_entropy(value: str) -> float:
    """Энтропия Шеннона в битах на символ."""
    if not value:
        return 0.0
    length = len(value)
    counts = Counter(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if any(term in lowered for term in SECRET_KEY_TERMS):
        return True
    return lowered.endswith("_key") or lowered.endswith("-key")


class Redactor:
    """Маскирует секреты в тексте, сохраняя структуру."""

    def __init__(self, extra_patterns: list[str] | None = None) -> None:
        self.extra_patterns = [re.compile(p) for p in (extra_patterns or [])]

    def redact(self, text: str) -> RedactionResult:
        masks: list[MaskInfo] = []

        def _pem(_match: re.Match) -> str:
            masks.append(
                MaskInfo(kind=MaskKind.PRIVATE_KEY, key="private_key"))
            return REDACTED

        text = PEM_RE.sub(_pem, text)

        out = [
            self._mask_line(line, lineno, masks)
            for lineno, line in enumerate(text.split("\n"), start=1)
        ]
        return RedactionResult(masked_text="\n".join(out), masks=masks)

    def redact_file(self, path: Path) -> RedactionResult:
        return self.redact(path.read_text(encoding="utf-8"))

    def _mask_line(self, line: str, lineno: int, masks: list[MaskInfo]) -> str:
        # KEY=VALUE
        match = ENV_KV_RE.match(line)
        if match and is_secret_key(match.group("key")):
            masks.append(MaskInfo(kind=MaskKind.KEY_NAME,
                         key=match.group("key"), line=lineno))
            return f"{match.group('key')}={REDACTED}"

        # KEY: VALUE (yaml-подобные)
        match = YAML_KV_RE.match(line)
        if match and is_secret_key(match.group("key")):
            masks.append(MaskInfo(kind=MaskKind.KEY_NAME,
                         key=match.group("key"), line=lineno))
            return f"{match.group('key')}: {REDACTED}"

        # "key": "value" (json)
        def _json(match: re.Match) -> str:
            if is_secret_key(match.group("key")):
                masks.append(MaskInfo(kind=MaskKind.KEY_NAME,
                             key=match.group("key"), line=lineno))
                return f'"{match.group("key")}": "{REDACTED}"'
            return match.group(0)

        line = JSON_KV_RE.sub(_json, line)

        # URL с учётными данными: маскируем только пароль.
        def _url(match: re.Match) -> str:
            masks.append(MaskInfo(kind=MaskKind.CONNECTION_STRING,
                         key="url_password", line=lineno))
            return f"{match.group('prefix')}{REDACTED}{match.group('suffix')}"

        line = URL_CREDS_RE.sub(_url, line)

        # JWT
        def _jwt(_match: re.Match) -> str:
            masks.append(MaskInfo(kind=MaskKind.JWT, key="jwt", line=lineno))
            return REDACTED

        line = JWT_RE.sub(_jwt, line)

        # Ключи провайдеров
        for name, pattern in PROVIDER_PATTERNS:
            def _provider(match: re.Match, name: str = name) -> str:
                masks.append(
                    MaskInfo(kind=MaskKind.PROVIDER_KEY, key=name, line=lineno))
                return REDACTED

            line = pattern.sub(_provider, line)

        # Высокоэнтропийные токены
        def _token(match: re.Match) -> str:
            if shannon_entropy(match.group(0)) >= ENTROPY_THRESHOLD:
                masks.append(MaskInfo(kind=MaskKind.HIGH_ENTROPY,
                             key="high_entropy", line=lineno))
                return REDACTED
            return match.group(0)

        line = TOKEN_RE.sub(_token, line)

        # Пользовательские паттерны из конфига
        for pattern in self.extra_patterns:
            def _custom(match: re.Match, pattern: re.Pattern = pattern) -> str:
                masks.append(MaskInfo(kind=MaskKind.CUSTOM,
                             key=pattern.pattern, line=lineno))
                return REDACTED

            line = pattern.sub(_custom, line)

        return line
