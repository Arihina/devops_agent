"""Repair Synthesizer: артефакт + ошибка сборки → исправленный артефакт."""

from __future__ import annotations

from devops_agent.llm import LLMGateway

_SYSTEM = """\
Ты — DevOps-инженер. Исправь Dockerfile по ошибке сборки.
Верни ТОЛЬКО исправленный Dockerfile целиком, без markdown-разметки и пояснений.
Сохрани структуру (многостадийность, non-root, порядок слоёв) — меняй только то,
что нужно для устранения ошибки.
"""


class RepairSynthesizer:
    """Патч Dockerfile по логу сборки."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def repair_dockerfile(self, dockerfile: str, error_log: str) -> str:
        user = (
            "Текущий Dockerfile:\n"
            f"{dockerfile}\n\n"
            "Ошибка сборки:\n"
            f"{error_log}\n\n"
            "Исправленный Dockerfile:"
        )
        result = self.gateway.complete(_SYSTEM, user, temperature=0.2)
        return _strip_fences(result.text)


def _strip_fences(text: str) -> str:
    """Снять markdown-обёртку ```dockerfile ... ```, если модель её добавила."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
