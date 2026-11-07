# DevOps Agent

CLI-агент для генерации и диагностики инфраструктурного обвеса Python-бэкенда: Dockerfile, docker-compose, CI-workflow и разбор упавших сборок.

Агент работает **локально на машине разработчика**. LLM запускается через [ollama](https://ollama.com) — код и логи не покидают компьютер.

---

## Что умеет

- **Определять стек проекта** (`profile`) — Python-версия, пакетный менеджер, фреймворк, точка входа, порт, миграции, внешние сервисы, переменные окружения.
- **Маскировать секреты** (`redact`) перед отправкой чего-либо в модель.
- **Аудировать существующие артефакты** (`audit`) — 6 гейтов проверки, включая реальный `docker build` и запуск контейнера.
- **Генерировать артефакты** (`scaffold`) — Dockerfile, docker-compose, CI-workflow, с итеративной починкой через LLM.
- **Разбирать упавшие сборки** (`diagnose`) — лог → корневая причина → предложенный патч.
- **Объяснять артефакты** (`explain`).

---

## Установка

### Требования

- **Python 3.12+** (агент зафиксирован на 3.12).
- **uv** — менеджер зависимостей.
- **Docker** — для гейтов сборки/запуска (без него аудит/генерация деградируют до статики).
- **ollama** и модели (см. ниже).

### 1. uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

### 2. Клонировать и установить зависимости

```bash
git clone <репозиторий> devops-agent
cd devops-agent
uv python pin 3.12
uv sync
```

### 3. ollama и модели

```bash
# установить ollama: https://ollama.com/download
ollama pull qwen2.5-coder:14b   # рабочая модель для итераций
ollama pull qwen3-coder:30b     # финальная генерация
```

Модели настраиваются в конфиге (`generation.model` / `generation.final_model`).

> На видеокарте 16 ГБ `qwen3-coder:30b` (MoE) частично уйдёт в RAM — будет медленнее, но работает. `qwen2.5-coder:14b` влезает целиком.

### 4. Опционально — линтеры для полного Lint Gate

```bash
# hadolint — линт Dockerfile
# actionlint — линт GitHub Actions
```

Без них Lint Gate работает в базовом режиме (синтаксис + `docker compose config`).

---

## Быстрый старт

```bash
cd ~/devops-agent

# посмотреть команды
uv run devops-agent --help

# инициализировать агента в целевом проекте
uv run devops-agent init --root ~/my-backend

# определить стек проекта
uv run devops-agent profile --root ~/my-backend

# аудит существующего Dockerfile (со сборкой)
uv run devops-agent audit --root ~/my-backend

# сгенерировать Dockerfile (LLM + сборка + починка)
uv run devops-agent scaffold docker --root ~/my-backend --diff-only

# разобрать упавшую сборку
uv run devops-agent diagnose 'error: pg_config executable not found'

# объяснить существующий файл
uv run devops-agent explain Dockerfile --root ~/my-backend
```

> Команду `uv run devops-agent ...` нужно запускать из папки агента (где `.venv`). На тестируемый проект указывает флаг `--root`.

---

## Команды

Все команды принимают `--root/-r` — корень целевого репозитория (по умолчанию текущая директория). `--version/-V` — версия агента.

| Команда | Назначение |
|---|---|
| `init` | создать `.devopsagent/` и конфиг |
| `profile` | показать определённый `StackProfile` |
| `redact <файл\|текст>` | замаскировать секреты, показать текст для модели |
| `audit` | проверить существующие артефакты |
| `scaffold docker \| ci \| compose` | сгенерировать артефакт |
| `diagnose <лог>` | разобрать сбой |
| `explain <артефакт>` | объяснить файл |
| `report` | метрики + сводка последнего прогона |
| `mappings init \| show \| edit \| add-apt` | управлять справочными таблицами |

### `init`

```bash
uv run devops-agent init --root ~/my-backend
uv run devops-agent init --root ~/my-backend --force   # пересоздать конфиг
```

Создаёт `.devopsagent/` с `config.toml`, `state.json`, `signatures/`, `runs/`.

### `profile`

```bash
uv run devops-agent profile --root ~/my-backend
```

Выводит `StackProfile`: Python, пакетный менеджер, фреймворк, точка входа, порт, миграции, внешние сервисы, apt-зависимости, переменные окружения, найденные артефакты. Работает без LLM.

### `redact`

```bash
uv run devops-agent redact ~/my-backend/.env            # файл
uv run devops-agent redact 'DB_PASSWORD=secret'         # текст
uv run devops-agent redact ~/.env --report              # + что замаскировано
```

Показывает текст, который уйдёт в модель (секреты заменены `<REDACTED>`).

### `audit`

```bash
uv run devops-agent audit --root ~/my-backend           # полный: статика + сборка + запуск
uv run devops-agent audit --root ~/my-backend --no-build # только статика
uv run devops-agent audit --root ~/my-backend --verbose  # живой вывод docker build
uv run devops-agent audit --root ~/my-backend --record   # + отчёт и метрики
```

Прогоняет гейты по существующим артефактам. Код возврата `1`, если есть findings уровня `error` — пригодно как pre-commit hook.

### `scaffold`

```bash
uv run devops-agent scaffold docker --root ~/my-backend --diff-only  # LLM + сборка + починка
uv run devops-agent scaffold docker --root ~/my-backend --dry-run    # план без вызова LLM
uv run devops-agent scaffold compose --root ~/my-backend --diff-only # детерминированно
uv run devops-agent scaffold ci --root ~/my-backend --diff-only      # детерминированно
```

- `scaffold docker` — LLM заполняет спецификацию, код собирает многостадийный Dockerfile, затем Build Gate; при ошибке — починка (до `generation.max_iterations`).
- `--diff-only` — показать, не писать файл. Без него файл пишется, если не существует (существующий не перезаписывается).

### `diagnose`

```bash
uv run devops-agent diagnose build.log                       # файл
uv run devops-agent diagnose 'error: No space left on device' # текст
uv run devops-agent diagnose build.log --record              # + отчёт и метрики
```

Сначала детерминированное сопоставление с базой сигнатур, затем LLM для остатка. В выводе честно указан источник: **сигнатура** (высокая уверенность) или **модель** (гипотеза).

### `explain`

```bash
uv run devops-agent explain Dockerfile --root ~/my-backend
```

LLM объясняет, что делает файл и почему.

### `report`

```bash
uv run devops-agent report --root ~/my-backend
```

Показывает накопленные метрики и сводку последнего прогона.

---

## Конфигурация

Файл `.devopsagent/config.toml` (создаётся `init`). Приоритет значений: **дефолты → config.toml → переменные окружения → флаги**.

| Секция | Что настраивает |
|---|---|
| `discovery` | переопределения автоопределения стека |
| `artifacts` | какие типы генерировать, целевые пути, режим при конфликте |
| `gates` | порог размера образа, неотключаемые правила |
| `generation` | модели, лимит итераций, бюджет токенов |
| `execution` | таймауты сборки/запуска, контейнерный движок |
| `redaction` | доп. паттерны, исключаемые файлы, предпросмотр |
| `output` | формат диффов, детализация отчёта |

Переменные окружения: `DEVOPSAGENT_<СЕКЦИЯ>__<ПОЛЕ>`, например `DEVOPSAGENT_GENERATION__MODEL=qwen3:8b`.

---

## Расширение базы сигнатур

Пользователь может добавлять собственные сигнатуры сбоев — детерминированные правила, которые распознаются **до** обращения к модели (дёшево и надёжно).

### Как добавить

Создайте JSON-файл в `.devopsagent/signatures/` целевого проекта:

```json
{
  "id": "my-service-error",
  "pattern": "custom error code 999",
  "cause_class": "наш специфичный сбой",
  "typical_fix": "Перезапустите сервис и проверьте конфиг."
}
```

Можно положить и массив объектов в один файл. Сигнатуры подхватываются автоматически — перезапуск не нужен.

### Поля

| Поле | Назначение |
|---|---|
| `id` | уникальный идентификатор сигнатуры |
| `pattern` | регулярное выражение (без учёта регистра); простая строка работает как «содержит» |
| `cause_class` | класс корневой причины (гипотеза) |
| `typical_fix` | типовое исправление |

> В JSON обратная косая черта экранируется: regex `\d+` пишется как `"\\d+"`.
> Простые литеральные фразы (`No space left on device`) экранирования не требуют.

Порядок сопоставления: **встроенные сигнатуры → пользовательские** (по имени файла). Каждый случай, где модель дала верный диагноз, — кандидат на превращение в сигнатуру.

---

## Справочные таблицы (mappings)

Стандартная информация (какой apt-пакет нужен Python-пакету, какой образ у postgres/kafka, какой порт у фреймворка) хранится в справочных таблицах и настраивается через `.devopsagent/mappings.json`.

```bash
uv run devops-agent mappings init --root ~/my-backend        # создать шаблон
uv run devops-agent mappings show --root ~/my-backend        # показать эффективные таблицы
uv run devops-agent mappings edit --root ~/my-backend        # открыть в $EDITOR
uv run devops-agent mappings add-apt mypackage libcustom-dev --root ~/my-backend
```

Три таблицы:

| Ключ | Что описывает |
|---|---|
| `apt_map` | Python-пакет → apt-пакеты (для сборки) |
| `services` | внешний сервис → образ, порт, env (для docker-compose) |
| `frameworks` | фреймворк → пакет-маркер и порт по умолчанию |

Можно указать только то, что меняешь/добавляешь — остальное берётся из встроенных. Пример (поменять образ kafka):

```json
{
  "services": {
    "kafka": {
      "name": "broker",
      "image": "registry.local/kafka:3.8",
      "port": 9092,
      "env": {},
      "app_env": {"KAFKA_BOOTSTRAP_SERVERS": "broker:9092"}
    }
  }
}
```

---

## Глоссарий терминов

- **Артефакт (Artifact)** — инфраструктурный файл в репозитории: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, CI-workflow. То, что агент генерирует или проверяет (не код приложения).
- **Гейт (Gate)** — контрольная точка качества: проверка «прошёл/не прошёл» с вердиктом. Гейтов шесть: **Lint** (синтаксис/структура), **Build** (образ собирается), **Runtime** (контейнер стартует и отвечает), **Security** (non-root, нет `latest`, нет `ADD` по URL, нет секретов), **Size** (размер образа), **Reproducibility** (версии зафиксированы).
- **Вердикт (Verdict)** — результат гейта: `pass` / `fail` / `warn` / `reject`.
- **Finding** — замечание аудита: правило, серьёзность (`error`/`warning`/`info`), местоположение, предложение исправить.
- **StackProfile** — нормализованное описание проекта: версия Python, пакетный менеджер, фреймворк, точка входа, порт, миграции, внешние сервисы, системные зависимости.
- **Discovery** — детерминированный слой, извлекающий `StackProfile`, зависимости, переменные окружения и список артефактов (без LLM).
- **Redaction Layer** — слой маскирования секретов (по именам ключей, формату, энтропии) перед отправкой текста в модель; сохраняет структуру, режет только значения.
- **Сигнатура (FailureSignature)** — известный сбой: паттерн (regex), класс причины, типовое исправление. База сигнатур — `.devopsagent/signatures/*.json`.
- **Диагноз (Diagnosis)** — результат разбора сбоя: гипотеза, уверенность, предложенное исправление, источник (`signature` или `model`).
- **Скелет (Skeleton)** — фиксированная структура артефакта (многостадийная сборка, non-root, порядок слоёв). Модель заполняет только переменные части.
- **Петля починки (Repair loop)** — итеративный цикл: синтез → Build Gate → починка через LLM → повтор, до лимита итераций.
- **Read-only контракт** — агент производит файлы и диффы, но не применяет изменения к инфраструктуре (нет `apply`/`push`/`deploy`). Разработчик ревьюит и коммитит сам.

---

## Архитектура (кратко)

```
CLI (Typer + Rich)
  └─ Оркестраторы: scaffold / audit / diagnose
       ├─ Discovery     (детерминированно, без LLM)
       ├─ Generation    (LLM: синтез и починка)
       ├─ Validation    (гейты: статика, docker build, запуск)
       ├─ Diagnosis     (сигнатуры + LLM)
       └─ Redaction Layer (всё, что уходит в модель)
```

---

## Границы (что агент НЕ делает)

- Kubernetes/Helm, Terraform и любой IaC для облаков.
- Применение изменений к живой системе (только файлы и диффы).
- Мониторинг, алерты, разбор production-инцидентов.
- Управление секретами и интеграция с vault.
- Multi-repo и монорепозитории.
- Языки, кроме Python.

---

## Коды возврата

| Код | Значение |
|---|---|
| `0` | успех |
| `1` | гейты не пройдены или findings уровня `error` (пригодно для pre-commit) |
| `2` | ошибка конфигурации или окружения |
