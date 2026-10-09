"""State Store: `state.json` с хешами профиля и статусами артефактов."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from devops_agent.core.contracts import ArtifactType

SCHEMA_VERSION = 1


class ArtifactStatus(BaseModel):
    """Статус одного артефакта в рабочем дереве."""

    type: ArtifactType
    target_path: str
    status: Literal["missing", "accepted", "rejected"] = "missing"
    content_hash: str = ""
    updated_at: str = ""


class State(BaseModel):
    """Машинночитаемое состояние агента (state.json)."""

    schema_version: int = SCHEMA_VERSION
    stack_profile_hash: str = ""
    artifacts: dict[str, ArtifactStatus] = Field(default_factory=dict)
    last_run: str = ""


class StateStore:
    """Чтение и запись state.json."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> State:
        if self.path.is_file():
            return State.model_validate_json(self.path.read_text(encoding="utf-8"))
        return State()

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
