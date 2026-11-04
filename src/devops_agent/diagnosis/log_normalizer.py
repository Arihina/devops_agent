"""Log Normalizer: сырой лог → структура (этап, код возврата, фрагмент ошибки)."""

from __future__ import annotations

import re

from pydantic import BaseModel

ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

ERROR_PATTERNS = [
    r"\berror\b",
    r"\bfailed\b",
    r"\bfailure\b",
    r"\bexception\b",
    r"\btraceback\b",
    r"\bcannot\b",
    r"\bnot found\b",
    r"\bdenied\b",
    r"\bE\d{4}\b",
]


class NormalizedLog(BaseModel):
    """Нормализованный лог."""

    text: str = ""
    error_fragment: str = ""
    exit_code: int | None = None
    ansi_removed: int = 0
    progress_lines_removed: int = 0


class LogNormalizer:
    """Отсеивает шум: ANSI, прогресс-бары, повторы."""

    def normalize(self, raw: str) -> NormalizedLog:
        ansi_count = raw.count("\x1b")
        text = ANSI_CSI_RE.sub("", raw)
        text = ANSI_OSC_RE.sub("", text)

        lines: list[str] = []
        progress_removed = 0
        for line in text.splitlines():
            if "\r" in line:
                # прогресс-бары: берём только финальное состояние строки
                line = line.split("\r")[-1]
                progress_removed += 1
            lines.append(line)

        # склеиваем последовательные повторы
        deduped: list[str] = []
        for line in lines:
            if deduped and deduped[-1] == line:
                continue
            deduped.append(line)

        error_lines = [
            line for line in deduped
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in ERROR_PATTERNS)
        ]
        return NormalizedLog(
            text="\n".join(deduped),
            error_fragment="\n".join(error_lines[:20]),
            exit_code=self._detect_exit_code("\n".join(deduped)),
            ansi_removed=ansi_count,
            progress_lines_removed=progress_removed,
        )

    @staticmethod
    def _detect_exit_code(text: str) -> int | None:
        match = re.search(
            r"(?:exit code|exit status|exited with(?: code)?)\s*[:=]?\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        return int(match.group(1)) if match else None
