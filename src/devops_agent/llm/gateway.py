"""LLM Gateway: единая точка обращения к модели.

Обращается к локальной ollama через OpenAI-совместимый эндпоинт, добавляет
ретраи, таймауты, учёт токенов и кеш по хешу промпта. Отсюда же — строгий
структурный вывод (`complete_json`) для заполнения скелетов.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Ошибка обращения к модели после исчерпания ретраев."""


@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False


class LLMGateway:
    """Тонкий клиент к модели с ретраями, таймаутом и кешем."""

    def __init__(
        self,
        model: str = "qwen2.5-coder:14b",
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        timeout: float = 600.0,
        max_retries: int = 3,
    ) -> None:
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self.model = model
        self.max_retries = max_retries
        self._cache: dict[str, str] = {}

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> Completion:
        """Обычный текстовый ответ."""
        key = self._key(system, user)
        if key in self._cache:
            return Completion(text=self._cache[key], model=self.model, cached=True)

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                text = response.choices[0].message.content or ""
                usage = response.usage
                self._cache[key] = text
                return Completion(
                    text=text,
                    model=self.model,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0),
                    completion_tokens=getattr(usage, "completion_tokens", 0),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(2 ** attempt)

        raise LLMError(
            f"модель {self.model} не ответила после {self.max_retries} попыток: {last_error}"
        )

    def complete_json(
        self,
        model_cls: type[T],
        system: str,
        user: str,
        temperature: float = 0.1,
    ) -> T:
        """Структурный вывод: JSON → валидация в Pydantic-модель."""
        system_json = (
            system
            + "\n\nОтвечай ТОЛЬКО валидным JSON-объектом, без markdown-разметки и пояснений."
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_json},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                text = response.choices[0].message.content or ""
                return model_cls.model_validate(_extract_json(text))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                time.sleep(2 ** attempt)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(2 ** attempt)

        raise LLMError(
            f"не удалось получить валидный JSON от {self.model}: {last_error}"
        )

    def _key(self, system: str, user: str) -> str:
        return hashlib.sha256(f"{self.model}\n{system}\n{user}".encode()).hexdigest()


def _extract_json(text: str) -> dict:
    """Вытащить JSON-объект из ответа модели (снимает ```json-обёртки)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    return json.loads(stripped[start : end + 1])
