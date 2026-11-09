# Доска задач

Правило: **одна строка на один `TASK-ID`**. Статусы меняются на месте, дубли запрещены.

- `dev_status`: `PLANNED`, `IN_PROGRESS`, `READY_FOR_REVIEW`
- `audit_status`: `PENDING`, `PASS`, `PASS WITH WARNINGS`, `FAIL`, `NOT VERIFIED`
- `owner_status`: `PENDING`, `ACCEPTED`, `ACCEPTED WITH LIMITATIONS`

| task_id | title | assignee | reviewer | dev_status | audit_status | owner_status | commit_ref | notes |
|---|---|---|---|---|---|---|---|---|
| TASK-000 | Каркас репозитория, Git, AGENTS.md, система координации и check_coordination.py | Sonnet-Staff | Argon-Judge | READY_FOR_REVIEW | PASS | ACCEPTED | d6e54f7 | Неделя 1 |
| TASK-001 | JSON-схемы состояния, графа доказательств и решений в schemas/ | Opus-Core | Argon-Judge | READY_FOR_REVIEW | PASS | ACCEPTED | c2b3aca | Неделя 1 |
| TASK-002 | Ядро Python CLI tools/strategist_cli.py и unit-тесты | Opus-Core | Argon-Judge | READY_FOR_REVIEW | PASS | ACCEPTED | b8dca7a | Неделя 1 |
| TASK-003 | Хук автовосстановления сессии .agents/hooks.json | Sonnet-Staff | Argon-Judge | READY_FOR_REVIEW | PASS | ACCEPTED | d6f669c | Неделя 1 |
| TASK-004 | Оркестратор agent/runtime-instructions.md, база knowledge/ и 4 базовых навыка в skills/ | Opus-Mind | Argon-Judge | READY_FOR_REVIEW | PASS | ACCEPTED | db0ffdc | Неделя 1 |
| TASK-005 | Продуктовые субагенты в agents/ и тренировочный кейс в projects/demo_mvp/ | Opus-Mind | Argon-Judge | READY_FOR_REVIEW | PASS | ACCEPTED | cf9eaa8 | Неделя 1 |
| TASK-006 | Сквозные приёмочные испытания T01–T12 и релиз MVP | Argon-Judge | Argon-Prime | PLANNED | PENDING | PENDING | - | Неделя 1 |
