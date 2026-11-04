"""Explain: объяснение существующего артефакта через LLM."""

from __future__ import annotations

from devops_agent.llm import LLMGateway

_SYSTEM = """\
Ты — DevOps-инженер. Объясни, что делает этот файл и почему он так устроен.
Говори по делу: назначение, ключевые решения, на что обратить внимание.
Не выдумывай детали, которых нет в файле.
"""


def explain_artifact(content: str, name: str, gateway: LLMGateway) -> str:
    user = f"Файл: {name}\n\n{content}"
    return gateway.complete(_SYSTEM, user).text
