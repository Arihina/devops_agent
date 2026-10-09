"""Reporter: отчёт прогона в human (report.md) и machine (report.json) форматах."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from devops_agent.core.contracts import Artifact, Diagnosis, Finding
from devops_agent.core.paths import Paths


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Report(BaseModel):
    """Машинночитаемый отчёт прогона (report.json)."""

    command: str
    status: Literal["success", "failed", "partial"] = "success"
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: _utcnow().isoformat())


class Reporter:
    """Запись и чтение отчётов в `.devopsagent/runs/<timestamp>/`."""

    RUN_SUBDIRS = ("diffs", "rejected", "prompts", "raw")

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def write(self, report: Report, run_id: str | None = None) -> Path:
        """Записать отчёт в новый run-каталог и вернуть его путь."""
        run_id = run_id or _utcnow().strftime("%Y%m%d-%H%M%S")
        run_dir = self.paths.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        for sub in self.RUN_SUBDIRS:
            (run_dir / sub).mkdir(exist_ok=True)
        (run_dir / "report.json").write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (run_dir / "report.md").write_text(self.render_markdown(report), encoding="utf-8")
        return run_dir

    def latest(self) -> tuple[str, Report] | None:
        """Вернуть (run_id, Report) последнего прогона или None."""
        if not self.paths.runs_dir.is_dir():
            return None
        reports = sorted(
            self.paths.runs_dir.glob("*/report.json"),
            key=lambda p: p.parent.name,
        )
        if not reports:
            return None
        latest_path = reports[-1]
        report = Report.model_validate_json(latest_path.read_text(encoding="utf-8"))
        return latest_path.parent.name, report

    def render_markdown(self, report: Report) -> str:
        """Собрать человекочитаемую сводку в Markdown."""
        lines: list[str] = [
            f"# Отчёт прогона: {report.command}",
            "",
            f"- **Статус:** {report.status}",
            f"- **Время:** {report.created_at}",
            "",
            report.summary if report.summary else "_Сводка не задана._",
            "",
            f"## Findings ({len(report.findings)})",
        ]
        if report.findings:
            lines.extend([
                "",
                "| Правило | Серьёзность | Расположение | Предложение |",
                "|---|---|---|---|",
            ])
            for finding in report.findings:
                lines.append(
                    f"| {finding.rule} | {finding.severity} | {finding.location} | "
                    f"{finding.suggestion or '—'} |"
                )
        else:
            lines.extend(["", "_Нет._"])
        lines.append("")

        lines.append(f"## Артефакты ({len(report.artifacts)})")
        if report.artifacts:
            lines.append("")
            for artifact in report.artifacts:
                lines.append(
                    f"- **{artifact.type}** → `{artifact.target_path}` "
                    f"(итерация {artifact.iteration})"
                )
        else:
            lines.extend(["", "_Нет._"])
        lines.append("")

        lines.append(f"## Диагнозы ({len(report.diagnoses)})")
        if report.diagnoses:
            lines.append("")
            for diagnosis in report.diagnoses:
                lines.append(
                    f"- **{diagnosis.source}** ({diagnosis.confidence:.0%}): "
                    f"{diagnosis.hypothesis}"
                )
        else:
            lines.extend(["", "_Нет._"])

        return "\n".join(lines) + "\n"
