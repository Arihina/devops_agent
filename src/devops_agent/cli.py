"""CLI-слой.

Команды: init, profile, scaffold (docker/ci/compose), audit, diagnose,
explain, report.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
import time

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from devops_agent import __version__
from devops_agent.core.config import DEFAULT_CONFIG_TOML, load_config
from devops_agent.core.mappings import (
    BUILTIN_MAPPINGS,
    load_mappings,
    load_user_mappings,
    mappings_path,
    save_mappings,
)
from devops_agent.core.contracts import Severity, StackProfile
from devops_agent.core.paths import Paths, resolve_root
from devops_agent.core.reporter import COVERAGE_BOUNDARIES, Report, Reporter
from devops_agent.core.state import State, StateStore
from devops_agent.discovery import Discovery
from devops_agent.discovery.models import DiscoveryResult
from devops_agent.redaction import RedactionResult, Redactor
from devops_agent.diagnosis import DiagnoseResult, diagnose as run_diagnose
from devops_agent.diagnosis.explain import explain_artifact
from devops_agent.llm import LLMGateway
from devops_agent.validation import AuditResult, audit as run_audit
from devops_agent.validation.docker import DockerExecution
from devops_agent.generation.scaffold import (
    ScaffoldResult,
    scaffold_ci,
    scaffold_compose,
    scaffold_docker,
)
from devops_agent.generation.skeletons import deterministic_spec, render_dockerfile

app = typer.Typer(
    name="devops-agent",
    help="CLI-агент для генерации и диагностики инфраструктурного обвеса Python-бэкенда.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


def _root_option():
    """Опция --root: корень целевого репозитория (по умолчанию — cwd)."""
    return typer.Option(
        Path("."),
        "--root",
        "-r",
        help="Корень целевого репозитория (по умолчанию — текущая директория).",
    )


def _not_implemented(name: str, stage: int) -> None:
    console.print(f"[yellow]{name}[/] — будет реализовано на этапе {stage}.")
    raise typer.Exit(code=2)


def _write_report(
    paths: Paths,
    command: str,
    status: str,
    summary: str,
    findings=None,
    artifacts=None,
    diagnoses=None,
) -> None:
    """Записать отчёт прогона с границами покрытия (§7, §11)."""
    report = Report(
        command=command,
        status=status,
        summary=summary,
        findings=findings or [],
        artifacts=artifacts or [],
        diagnoses=diagnoses or [],
        coverage=COVERAGE_BOUNDARIES,
    )
    run_dir = Reporter(paths).write(report)
    console.print(f"[dim]Отчёт: {run_dir}/report.md[/dim]")


def _update_metrics(paths: Paths, update) -> None:
    """Применить изменение к метрикам и сохранить state.json."""
    store = StateStore(paths.state_file)
    state = store.load()
    update(state.metrics)
    store.save(state)


def _render_metrics(paths: Paths) -> None:
    """Вывести накопленные метрики (раздел 10)."""
    metrics = StateStore(paths.state_file).load().metrics
    coverage = metrics.signature_coverage
    table = Table(title="Метрики")
    table.add_column("Показатель", style="bold")
    table.add_column("Значение")
    table.add_row("Диагнозов всего", str(metrics.diagnoses_total))
    table.add_row(
        "Покрыто сигнатурами",
        f"{metrics.diagnoses_signature} ({coverage:.0%})" if coverage is not None else "—",
    )
    table.add_row("Scaffold принято/всего", f"{metrics.scaffold_accepted}/{metrics.scaffold_runs}")
    table.add_row(
        "Scaffold среднее итераций",
        f"{metrics.scaffold_iterations / metrics.scaffold_runs:.1f}" if metrics.scaffold_runs else "—",
    )
    table.add_row("Scaffold суммарное время", f"{metrics.scaffold_seconds:.1f} с")
    table.add_row("Audit прогонов", str(metrics.audit_runs))
    console.print(table)


def _render_discovery(result: DiscoveryResult, root: Path) -> None:
    """Rich-вывод результата Discovery для команды `profile`."""
    profile = result.profile

    console.print(f"[dim]Корень: {root}[/dim]")
    table = Table(title="StackProfile", show_header=False, title_style="bold")
    table.add_column("Поле", style="bold cyan")
    table.add_column("Значение")
    table.add_row("Python", profile.python_version or "—")
    table.add_row("Пакетный менеджер", profile.package_manager or "—")
    table.add_row("Фреймворк", profile.framework or "—")
    table.add_row("Точка входа", profile.entry_point or "—")
    table.add_row("Порт", str(profile.port)
                  if profile.port is not None else "—")
    table.add_row("Миграции", ", ".join(profile.migrations)
                  if profile.migrations else "—")
    table.add_row("Внешние сервисы", ", ".join(
        profile.external_services) if profile.external_services else "—")
    table.add_row(
        "Системные (apt)",
        ", ".join(
            profile.system_dependencies) if profile.system_dependencies else "—",
    )
    console.print(table)

    console.print(f"[bold]Пакеты:[/] {len(result.packages)}")

    if result.env_vars:
        env_table = Table(title="Переменные окружения (из кода)")
        env_table.add_column("Имя", style="bold")
        env_table.add_column("Тип")
        env_table.add_column("По умолчанию")
        env_table.add_column("Где")
        for var in result.env_vars:
            env_table.add_row(var.name, var.type or "?",
                              var.default or "", var.locations[0])
        console.print(env_table)
    else:
        console.print("[dim]Переменные окружения в коде не найдены.[/dim]")

    if result.artifacts:
        art_table = Table(title="Существующие артефакты")
        art_table.add_column("Тип", style="bold")
        art_table.add_column("Путь")
        for artifact in result.artifacts:
            art_table.add_row(artifact.type.value, artifact.path)
        console.print(art_table)
    else:
        console.print("[dim]Инфраструктурные артефакты не найдены.[/dim]")


def _render_masks(result: RedactionResult) -> None:
    """Rich-вывод списка замаскированных фрагментов для команды `redact`."""
    if not result.masks:
        console.print("[dim]Секретов не найдено.[/dim]")
        return
    table = Table(title=f"Замаскировано: {len(result.masks)}")
    table.add_column("Тип", style="bold")
    table.add_column("Ключ")
    table.add_column("Строка")
    for mask in result.masks:
        table.add_row(mask.kind.value, mask.key or "—",
                      str(mask.line) if mask.line else "—")
    console.print(table)


def _render_audit(result: AuditResult) -> None:
    """Rich-вывод результата аудита для команды `audit`."""
    if not result.artifacts:
        console.print("[yellow]Инфраструктурных артефактов не найдено — нечего аудировать.[/yellow]")
        return

    verdict_icons = {
        "pass": "[green]✓ pass[/green]",
        "fail": "[red]✗ fail[/red]",
        "warn": "[yellow]! warn[/yellow]",
        "reject": "[red]✗ reject[/red]",
    }
    gate_table = Table(title="Гейты")
    gate_table.add_column("Гейт", style="bold")
    gate_table.add_column("Вердикт")
    gate_table.add_column("Причина")
    for gate_result in result.gates:
        gate_table.add_row(
            f"{gate_result.gate.value} ({gate_result.level.value})",
            verdict_icons[gate_result.verdict.value],
            gate_result.reason or "—",
        )
    console.print(gate_table)

    if result.findings:
        severity_style = {"error": "red", "warning": "yellow", "info": "dim"}
        finding_table = Table(title=f"Findings ({len(result.findings)})")
        finding_table.add_column("Серьёзность", style="bold")
        finding_table.add_column("Правило")
        finding_table.add_column("Расположение")
        finding_table.add_column("Предложение")
        for finding in result.findings:
            style = severity_style.get(finding.severity.value)
            severity = f"[{style}]{finding.severity.value}[/{style}]" if style else finding.severity.value
            finding_table.add_row(severity, finding.rule, finding.location, finding.suggestion or "—")
        console.print(finding_table)
    else:
        console.print("[green]Findings не найдены.[/green]")


@app.callback(invoke_without_command=True)
def _version_callback(
    version: bool = typer.Option(
        False, "--version", "-V", help="Показать версию и выйти."
    ),
) -> None:
    if version:
        console.print(f"devops-agent {__version__}")
        raise typer.Exit()


@app.command()
def init(
    root: Path = _root_option(),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Пересоздать .devopsagent/ с дефолтными config.toml и state.json.",
    ),
) -> None:
    """Создать .devopsagent/ и конфиг в корне репозитория."""
    paths = Paths(resolve_root(root))

    if paths.devops.exists() and not force:
        console.print(f"[yellow]Уже существует:[/] {paths.devops}")
        console.print("Используйте --force для пересоздания.")
        raise typer.Exit(code=2)

    paths.devops.mkdir(parents=True, exist_ok=True)
    paths.signatures_dir.mkdir(exist_ok=True)
    paths.runs_dir.mkdir(exist_ok=True)
    (paths.signatures_dir / ".gitkeep").touch(exist_ok=True)
    (paths.runs_dir / ".gitkeep").touch(exist_ok=True)

    if not paths.config_file.exists() or force:
        paths.config_file.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    if not paths.state_file.exists() or force:
        StateStore(paths.state_file).save(State())

    tree = Tree(f"[bold green].devopsagent[/] создан в {paths.devops}")
    tree.add("[bold]config.toml[/] — конфигурация")
    tree.add("[bold]state.json[/] — состояние (хеши профиля, статусы артефактов)")
    tree.add("[bold]signatures/[/] — база известных сигнатур сбоев")
    tree.add("[bold]runs/[/] — отчёты прогонов")
    console.print(tree)


@app.command()
def report(root: Path = _root_option()) -> None:
    """Показать метрики и сводку последнего прогона."""
    paths = Paths(resolve_root(root))
    _render_metrics(paths)
    reporter = Reporter(paths)
    latest = reporter.latest()
    if latest is None:
        console.print("[yellow]Прогонов пока нет.[/]")
        return
    _, report_obj = latest
    print(reporter.render_markdown(report_obj))


@app.command()
def profile(root: Path = _root_option()) -> None:
    """Показать определённый StackProfile без генерации."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    result = Discovery(paths.root, config).run()
    _render_discovery(result, paths.root)


@app.command()
def redact(
    target: str = typer.Argument(..., help="Файл или текст для маскирования."),
    root: Path = _root_option(),
    report: bool = typer.Option(
        False, "--report", help="Показать, что именно было замаскировано."
    ),
) -> None:
    """Замаскировать секреты и показать текст, который уйдёт в модель."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    redactor = Redactor(extra_patterns=config.redaction.extra_patterns)

    target_path = Path(target)
    if target_path.is_file():
        result = redactor.redact_file(target_path)
    else:
        result = redactor.redact(target)

    print(result.masked_text)
    if report:
        _render_masks(result)


@app.command()
def audit(
    root: Path = _root_option(),
    no_build: bool = typer.Option(
        False, "--no-build", help="Только статическая валидация (без сборки и запуска)."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Показывать живой вывод docker build."
    ),
    record: bool = typer.Option(
        False, "--record", help="Записать отчёт прогона и обновить метрики."
    ),
) -> None:
    """Проверить существующие артефакты и вернуть findings без изменений."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    console.print(f"[dim]Корень: {paths.root}[/dim]")

    if not no_build and not DockerExecution(config.execution.container_runtime).available():
        console.print("[yellow]Предупреждение: Docker недоступен — сборка/запуск будут пропущены.[/yellow]")

    result = run_audit(paths.root, config, skip_build=no_build, verbose=verbose)
    _render_audit(result)

    has_errors = any(f.severity == Severity.ERROR for f in result.findings)
    if record:
        _update_metrics(paths, lambda m: setattr(m, "audit_runs", m.audit_runs + 1))
        _write_report(
            paths,
            "audit",
            "failed" if has_errors else "success",
            f"Проверено артефактов: {len(result.artifacts)}, findings: {len(result.findings)}.",
            findings=result.findings,
        )

    if has_errors:
        raise typer.Exit(code=1)


@app.command()
def diagnose(
    log: str = typer.Argument(..., help="Путь к файлу лога или сам лог сбоя."),
    root: Path = _root_option(),
    record: bool = typer.Option(
        False, "--record", help="Записать отчёт прогона и обновить метрики."
    ),
) -> None:
    """Разобрать сбой: лог → корневая причина → предложенный патч."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    log_path = Path(log)
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = log
    result = run_diagnose(text, paths.root, config)
    _render_diagnosis(result)

    if record:
        is_signature = result.diagnosis.source.value == "signature"

        def update(metrics):
            metrics.diagnoses_total += 1
            if is_signature:
                metrics.diagnoses_signature += 1
            else:
                metrics.diagnoses_model += 1

        _update_metrics(paths, update)
        _write_report(
            paths,
            "diagnose",
            "success",
            f"Источник: {result.diagnosis.source.value}, уверенность {result.diagnosis.confidence:.0%}.",
            diagnoses=[result.diagnosis],
        )


@app.command()
def explain(
    artifact: str = typer.Argument(...,
                                   help="Путь к существующему артефакту."),
    root: Path = _root_option(),
) -> None:
    """Объяснить, что делает существующий файл и почему."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    artifact_path = paths.root / artifact
    if not artifact_path.is_file():
        console.print(f"[red]Файл не найден:[/red] {artifact_path}")
        raise typer.Exit(code=2)
    content = artifact_path.read_text(encoding="utf-8", errors="replace")
    gateway = LLMGateway(model=config.generation.model)
    print(explain_artifact(content, artifact, gateway))


def _render_diagnosis(result: DiagnoseResult) -> None:
    """Rich-вывод результата разбора сбоя (с честным разделением источника)."""
    d = result.diagnosis
    if d.source.value == "signature":
        source_label, style = "сигнатура", "green"
    else:
        source_label, style = "модель", "yellow"

    console.print(
        f"[bold]Диагноз[/bold] — источник: [{style}]{source_label}[/{style}], "
        f"уверенность {d.confidence:.0%}"
    )
    console.print(f"[bold]Гипотеза:[/bold] {d.hypothesis}")
    if d.proposed_diff:
        console.print("[bold]Исправление:[/bold]")
        print(d.proposed_diff)

    meta = []
    if d.source.value == "signature" and result.signature_id:
        meta.append(f"сигнатура: {result.signature_id}")
    if result.normalized.exit_code is not None:
        meta.append(f"exit code {result.normalized.exit_code}")
    if result.normalized.ansi_removed:
        meta.append(f"ANSI удалено: {result.normalized.ansi_removed}")
    if meta:
        console.print("[dim]" + "; ".join(meta) + "[/dim]")

    if d.source.value == "model" and result.redacted_text:
        console.print("[bold]Текст, ушедший в модель (после редкации):[/bold]")
        print(result.redacted_text)


def _render_dry_run(profile: StackProfile, spec) -> None:
    """Вывод плана для `scaffold docker --dry-run` (без вызова модели)."""
    console.print("[bold]Профиль:[/bold]")
    console.print(
        f"  Python {profile.python_version or '?'}, "
        f"{profile.package_manager or '?'}, {profile.framework or '?'}, "
        f"entrypoint={profile.entry_point or '?'}, port={profile.port or '?'}"
    )
    console.print("[bold]Детерминированная спецификация (без LLM):[/bold]")
    print(spec.model_dump_json(indent=2))
    console.print("[bold]Dockerfile из скелета:[/bold]")
    print(render_dockerfile(spec))


def _emit_scaffold(result: ScaffoldResult, target: Path, diff_only: bool, label: str) -> None:
    """Принять → записать/показать; отклонить → exit 1."""
    if not result.accepted:
        console.print(f"[red]Отклонён:[/red] {result.reason}")
        raise typer.Exit(code=1)
    if diff_only or target.exists():
        console.print(f"[dim]Предлагаемый {label} (не записан):[/dim]")
        print(result.content)
        if target.exists():
            console.print(f"[yellow]Файл {target} уже существует — не перезаписан.[/yellow]")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.content, encoding="utf-8")
        console.print(f"[green]Записан:[/green] {target}")
    console.print(f"[dim]Итераций: {result.iterations}[/dim]")


scaffold_app = typer.Typer(
    help="Сгенерировать инфраструктурные артефакты.", no_args_is_help=False
)


@scaffold_app.callback(invoke_without_command=True)
def _scaffold(ctx: typer.Context, root: Path = _root_option()) -> None:
    if ctx.invoked_subcommand is None:
        _not_implemented("scaffold (все артефакты)", 4)


@scaffold_app.command("docker")
def _scaffold_docker(
    root: Path = _root_option(),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Показать профиль и заготовку без вызова модели."
    ),
    diff_only: bool = typer.Option(
        False, "--diff-only", help="Не писать файл, только показать результат."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Живой вывод docker build."
    ),
    record: bool = typer.Option(
        False, "--record", help="Записать отчёт прогона и обновить метрики."
    ),
) -> None:
    """Сгенерировать Dockerfile."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    profile = Discovery(paths.root, config).run().profile

    if dry_run:
        console.print(f"[dim]Корень: {paths.root}[/dim]")
        _render_dry_run(profile, deterministic_spec(profile))
        return

    start = time.monotonic()
    result = scaffold_docker(paths.root, config, profile, verbose=verbose)
    elapsed = time.monotonic() - start
    _emit_scaffold(
        result,
        paths.root / config.artifacts.dockerfile_path,
        diff_only,
        config.artifacts.dockerfile_path,
    )

    if record:
        def update(metrics):
            metrics.scaffold_runs += 1
            if result.accepted:
                metrics.scaffold_accepted += 1
            metrics.scaffold_iterations += result.iterations
            metrics.scaffold_seconds += elapsed

        _update_metrics(paths, update)
        _write_report(
            paths,
            "scaffold docker",
            "success" if result.accepted else "failed",
            f"Принят: {result.accepted}, итераций: {result.iterations}, время: {elapsed:.1f} с.",
        )


@scaffold_app.command("ci")
def _scaffold_ci(
    root: Path = _root_option(),
    diff_only: bool = typer.Option(
        False, "--diff-only", help="Не писать файл, только показать результат."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Живой вывод внешних проверок."
    ),
    record: bool = typer.Option(
        False, "--record", help="Записать отчёт прогона."
    ),
) -> None:
    """Сгенерировать CI-workflow (без запуска на живом GitHub)."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    profile = Discovery(paths.root, config).run().profile
    result = scaffold_ci(paths.root, config, profile, verbose=verbose)
    _emit_scaffold(
        result,
        paths.root / config.artifacts.ci_path,
        diff_only,
        config.artifacts.ci_path,
    )
    if record:
        _write_report(paths, "scaffold ci", "success" if result.accepted else "failed", f"Принят: {result.accepted}.")


@scaffold_app.command("compose")
def _scaffold_compose(
    root: Path = _root_option(),
    diff_only: bool = typer.Option(
        False, "--diff-only", help="Не писать файл, только показать результат."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Живой вывод внешних проверок."
    ),
    record: bool = typer.Option(
        False, "--record", help="Записать отчёт прогона."
    ),
) -> None:
    """Сгенерировать docker-compose."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    profile = Discovery(paths.root, config).run().profile
    result = scaffold_compose(paths.root, config, profile, verbose=verbose)
    _emit_scaffold(
        result,
        paths.root / config.artifacts.compose_path,
        diff_only,
        config.artifacts.compose_path,
    )
    if record:
        _write_report(paths, "scaffold compose", "success" if result.accepted else "failed", f"Принят: {result.accepted}.")


mappings_app = typer.Typer(
    help="Справочные таблицы агента (пакет→apt, сервис→образ, фреймворк→порт).",
    no_args_is_help=True,
)


@mappings_app.command("init")
def _mappings_init(
    root: Path = _root_option(),
    force: bool = typer.Option(
        False, "--force", "-f", help="Перезаписать существующий mappings.json."
    ),
) -> None:
    """Создать .devopsagent/mappings.json с встроенными значениями (шаблон для правки)."""
    paths = Paths(resolve_root(root))
    path = mappings_path(paths.root)
    if path.is_file() and not force:
        console.print(f"[yellow]Уже существует:[/yellow] {path}")
        console.print("Используйте --force для перезаписи.")
        raise typer.Exit(code=2)
    save_mappings(paths.root, BUILTIN_MAPPINGS)
    console.print(f"[green]Создан шаблон:[/green] {path}")


@mappings_app.command("show")
def _mappings_show(root: Path = _root_option()) -> None:
    """Показать эффективные справочные таблицы (встроенные + пользовательские)."""
    paths = Paths(resolve_root(root))
    print(load_mappings(paths.root).model_dump_json(indent=2))


@mappings_app.command("edit")
def _mappings_edit(root: Path = _root_option()) -> None:
    """Открыть mappings.json в $EDITOR."""
    paths = Paths(resolve_root(root))
    path = mappings_path(paths.root)
    if not path.is_file():
        console.print("[yellow]mappings.json не найден — сначала `mappings init`.[/yellow]")
        raise typer.Exit(code=2)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    subprocess.run([editor, str(path)])


@mappings_app.command("add-apt")
def _mappings_add_apt(
    package: str = typer.Argument(..., help="Python-пакет, например psycopg2."),
    apt_packages: list[str] = typer.Argument(..., help="apt-пакеты, например libpq-dev."),
    root: Path = _root_option(),
) -> None:
    """Добавить соответствие «Python-пакет → apt-пакеты»."""
    paths = Paths(resolve_root(root))
    user = load_user_mappings(paths.root)
    user.apt_map[package] = list(apt_packages)
    save_mappings(paths.root, user)
    console.print(f"[green]Добавлено:[/green] {package} → {', '.join(apt_packages)}")


app.add_typer(scaffold_app, name="scaffold")
app.add_typer(mappings_app, name="mappings")
