# Регламент координации (Контур разработки)

Действует только в Режиме Б (см. `AGENTS.md`). Общая память команды — файлы этого каталога и Git.

## 1. Матрица полномочий

| Чат | Роль | Может создавать/изменять | Запрещено |
|---|---|---|---|
| `Argon-Prime` | Куратор / Архитектор | ТЗ и постановка задач, решения (`docs/decisions.md`), согласование с Owner | Подменять аудит; ставить `PASS` |
| `Sonnet-Staff` | Инфраструктура | `AGENTS.md`*, `CLAUDE.md`, `.cursorrules`, `README.md`, `.gitignore`, `.env.example`, `.agents/`, `docs/`, `tools/check_coordination.py`, `tests/unit/test_check_coordination.py`, каркас каталогов | Бизнес-логика в `tools/strategist_cli.py`; правка утверждённых `schemas/`; `PASS`/`ACCEPTED`; удаление `ТЗ.txt` |
| `Opus-Core` | Ядро | `schemas/`, `tools/strategist_cli.py`, Evidence Graph, анализатор таблиц, `tests/unit/`, `tests/integration/` | Править `AGENTS.md`, `skills/`, `agents/`; `PASS`/`ACCEPTED` |
| `Opus-Mind` | Навыки и субагенты | `agent/runtime-instructions.md`, `skills/`, `knowledge/`, `agents/`, `projects/demo_mvp/` | Править `schemas/`, `tools/`; `PASS`/`ACCEPTED` |
| `Argon-Judge` | Независимый аудитор | Только записи `AUDIT` в `review-handoff.md` и `audit_status` в `task-board.md` | Менять код, навыки, схемы (строго Read-Only) |

\* Изменение `AGENTS.md` — только с согласия Owner и фиксацией SHA-256 в `review-handoff.md`.

Владелец проекта (Owner) единолично выставляет `owner_status`.

## 2. Три независимых статуса задачи

| Поле | Кто ставит | Значения |
|---|---|---|
| `dev_status` | исполнитель | `PLANNED`, `IN_PROGRESS`, `READY_FOR_REVIEW` |
| `audit_status` | `Argon-Judge` | `PENDING`, `PASS`, `PASS WITH WARNINGS`, `FAIL`, `NOT VERIFIED` |
| `owner_status` | Owner | `PENDING`, `ACCEPTED`, `ACCEPTED WITH LIMITATIONS` |

Правила:
- Исполнитель **никогда** не ставит `audit_status: PASS*` и `owner_status: ACCEPTED*`.
- Переход в `READY_FOR_REVIEW` требует коммита и записи `HANDOFF` в `review-handoff.md` с реальным `commit_hash`.
- В `task-board.md` — **одна строка на `TASK-ID`**; статусы меняются на месте, дубли запрещены.

## 3. Журнал `review-handoff.md`

Append-only: существующие записи не удаляются и не редактируются; исправления — новой записью с `predecessor_ref`. Формат записи — в начале самого файла. Проверка: `python tools/check_coordination.py`.

## 4. Стандарт отчёта аудитора (`Argon-Judge`)

Каждое замечание обязано содержать 5 полей:

1. **Доказательство** — файл/строка, вывод команды, воспроизводимый шаг.
2. **Масштаб** — что и где затронуто.
3. **Серьёзность** — `Critical` / `High` / `Medium` / `Low`.
4. **Границы проверки** — что именно проверено и что не проверялось.
5. **Условие закрытия** — что должно измениться, чтобы замечание закрыто.

Допустимые вердикты: `PASS`, `PASS WITH WARNINGS`, `FAIL`, `NOT VERIFIED`.
