"""CLI-слой.

Команды: init, profile, scaffold (docker/ci/compose), audit, diagnose,
explain, report.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from devops_agent import __version__
from devops_agent.core.config import DEFAULT_CONFIG_TOML, load_config
from devops_agent.core.paths import Paths, resolve_root
from devops_agent.core.reporter import Reporter
from devops_agent.core.state import State, StateStore
from devops_agent.discovery import Discovery
from devops_agent.discovery.models import DiscoveryResult

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
    """Показать сводку последнего прогона."""
    reporter = Reporter(Paths(resolve_root(root)))
    latest = reporter.latest()
    if latest is None:
        console.print("[yellow]Прогонов пока нет.[/]")
        return
    _, report_obj = latest
    console.print(reporter.render_markdown(report_obj), markup=False)


@app.command()
def profile(root: Path = _root_option()) -> None:
    """Показать определённый StackProfile без генерации."""
    paths = Paths(resolve_root(root))
    config = load_config(paths.config_file)
    result = Discovery(paths.root, config).run()
    _render_discovery(result, paths.root)


@app.command()
def audit(root: Path = _root_option()) -> None:
    """Проверить существующие артефакты и вернуть findings без изменений."""
    _not_implemented("audit", 3)


@app.command()
def diagnose(
    log: str = typer.Argument(..., help="Путь к файлу лога или сам лог сбоя."),
    root: Path = _root_option(),
) -> None:
    """Разобрать сбой: лог → корневая причина → предложенный патч."""
    _not_implemented("diagnose", 5)


@app.command()
def explain(
    artifact: str = typer.Argument(...,
                                   help="Путь к существующему артефакту."),
    root: Path = _root_option(),
) -> None:
    """Объяснить, что делает существующий файл и почему."""
    _not_implemented("explain", 5)


scaffold_app = typer.Typer(
    help="Сгенерировать инфраструктурные артефакты.", no_args_is_help=False
)


@scaffold_app.callback(invoke_without_command=True)
def _scaffold(ctx: typer.Context, root: Path = _root_option()) -> None:
    if ctx.invoked_subcommand is None:
        _not_implemented("scaffold (все артефакты)", 4)


@scaffold_app.command("docker")
def _scaffold_docker(root: Path = _root_option()) -> None:
    """Сгенерировать Dockerfile и .dockerignore."""
    _not_implemented("scaffold docker", 4)


@scaffold_app.command("ci")
def _scaffold_ci(root: Path = _root_option()) -> None:
    """Сгенерировать CI-workflow."""
    _not_implemented("scaffold ci", 4)


@scaffold_app.command("compose")
def _scaffold_compose(root: Path = _root_option()) -> None:
    """Сгенерировать docker-compose."""
    _not_implemented("scaffold compose", 4)


app.add_typer(scaffold_app, name="scaffold")
