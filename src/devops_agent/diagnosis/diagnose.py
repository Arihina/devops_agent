"""Diagnose: лог → нормализация → редкация → сигнатура/LLM → диагноз."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from devops_agent.core.config import Config
from devops_agent.core.contracts import Diagnosis, DiagnosisSource
from devops_agent.diagnosis.log_normalizer import LogNormalizer, NormalizedLog
from devops_agent.diagnosis.root_cause import RootCauseAnalyst
from devops_agent.diagnosis.signatures import SignatureMatcher
from devops_agent.llm import LLMGateway
from devops_agent.redaction import Redactor

_SIGNATURE_CONFIDENCE = 0.9


class DiagnoseResult(BaseModel):
    """Результат разбора сбоя."""

    diagnosis: Diagnosis
    normalized: NormalizedLog
    redacted_text: str = ""
    signature_id: str = ""


def diagnose(log_text: str, root: Path, config: Config) -> DiagnoseResult:
    """Разобрать сбой: сначала сигнатуры (дёшево), затем LLM (для остатка)."""
    normalized = LogNormalizer().normalize(log_text)

    matcher = SignatureMatcher(root)
    match_text = normalized.error_fragment or normalized.text
    signature = matcher.match(match_text)
    if signature is not None:
        diagnosis = Diagnosis(
            hypothesis=signature.cause_class,
            confidence=_SIGNATURE_CONFIDENCE,
            proposed_diff=signature.typical_fix,
            source=DiagnosisSource.SIGNATURE,
        )
        return DiagnoseResult(
            diagnosis=diagnosis,
            normalized=normalized,
            redacted_text="",
            signature_id=signature.id,
        )

    # LLM получает только отредактированный текст.
    redacted = Redactor(config.redaction.extra_patterns).redact(normalized.text).masked_text
    gateway = LLMGateway(model=config.generation.model)
    diagnosis = RootCauseAnalyst(gateway).analyze(redacted)
    
    return DiagnoseResult(
        diagnosis=diagnosis,
        normalized=normalized,
        redacted_text=redacted,
    )
