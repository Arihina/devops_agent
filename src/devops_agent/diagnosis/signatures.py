"""Signature Matcher: база известных сигнатур сбоев.

Сначала — детерминированное сопоставление регулярками; LLM вызывается только
для остатка. База пополняется файлами `.devopsagent/signatures/*.json`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from devops_agent.core.contracts import FailureSignature

BUILTIN_SIGNATURES: list[FailureSignature] = [
    FailureSignature(
        id="missing-pg-config",
        pattern=r"pg_config\s+(?:executable\s+)?not found",
        cause_class="не хватает libpq-dev — psycopg2 собирается из исходников",
        typical_fix="Добавьте libpq-dev в apt-пакеты или используйте psycopg2-binary.",
    ),
    FailureSignature(
        id="missing-c-header",
        pattern=r"fatal error:\s+\S+\.h:\s+No such file",
        cause_class="не хватает системных заголовков для C-расширения",
        typical_fix="Установите соответствующий *-dev пакет через apt.",
    ),
    FailureSignature(
        id="permission-denied",
        pattern=r"permission denied|EACCES|not permitted",
        cause_class="нет прав доступа",
        typical_fix="Проверьте права файла/каталога и владельца процесса.",
    ),
    FailureSignature(
        id="version-conflict",
        pattern=r"conflicting dependenc|ResolutionImpossible|incompatible",
        cause_class="конфликт версий зависимостей",
        typical_fix="Зафиксируйте совместимые версии (== или lock-файл).",
    ),
    FailureSignature(
        id="disk-full",
        pattern=r"No space left on device",
        cause_class="закончилось место на диске",
        typical_fix="Освободите место; в CI — увеличьте диск или используйте кеш.",
    ),
    FailureSignature(
        id="timeout",
        pattern=r"timed out|TimeoutError|ETIMEDOUT|deadline exceeded",
        cause_class="таймаут операции",
        typical_fix="Увеличьте таймаут или разбейте операцию на части.",
    ),
    FailureSignature(
        id="image-not-found",
        pattern=r"manifest .* not found|pull access denied|repository does not exist",
        cause_class="образ не найден или нет прав на pull",
        typical_fix="Проверьте имя/тег образа и доступ к реестру.",
    ),
    FailureSignature(
        id="network-unreachable",
        pattern=r"Could not resolve host|Name or service not known|Connection refused|Temporary failure in name resolution",
        cause_class="сетевая недоступность",
        typical_fix="Проверьте сеть/DNS и доступ к внешним хостам.",
    ),
    FailureSignature(
        id="port-in-use",
        pattern=r"address already in use|port is already allocated|bind: .* in use",
        cause_class="порт уже занят",
        typical_fix="Освободите порт или смените порт приложения.",
    ),
    FailureSignature(
        id="out-of-memory",
        pattern=r"Killed process|OutOfMemory|OOM|MemoryError|cannot allocate memory",
        cause_class="нехватка памяти",
        typical_fix="Увеличьте лимит памяти или оптимизируйте потребление.",
    ),
    FailureSignature(
        id="module-not-found",
        pattern=r"ModuleNotFoundError: No module named",
        cause_class="не установлен Python-модуль",
        typical_fix="Добавьте пакет в зависимости.",
    ),
    FailureSignature(
        id="syntax-error",
        pattern=r"SyntaxError|IndentationError",
        cause_class="синтаксическая ошибка в коде",
        typical_fix="Исправьте синтаксис в указанном файле.",
    ),
]


class SignatureMatcher:
    """Сопоставляет лог с базой сигнатур; первое совпадение — ответ."""

    def __init__(self, root: Path) -> None:
        self.signatures = list(BUILTIN_SIGNATURES)
        self.signatures.extend(self._load_from_dir(root / ".devopsagent" / "signatures"))

    def match(self, text: str) -> FailureSignature | None:
        for signature in self.signatures:
            if re.search(signature.pattern, text, re.IGNORECASE):
                return signature
        return None

    @staticmethod
    def _load_from_dir(directory: Path) -> list[FailureSignature]:
        found: list[FailureSignature] = []
        if not directory.is_dir():
            return found
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else [data]
                for item in items:
                    found.append(FailureSignature(**item))
            except Exception:  # noqa: BLE001 — пропускаем некорректные файлы
                continue
        return found
