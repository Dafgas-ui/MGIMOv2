# MGIMOv3 — «Стратег Фабрики продуктов»

ИИ-агент для руководителя цифрового продукта МегаФона (MGIMO AI Challenge 2026): от размытого запроса к проверяемой картине, вариантам и согласованным продуктовой и коммуникационной стратегиям. Это папка с инструкциями, навыками и знаниями — открывается в Cursor, Claude Code, Antigravity и т.п.

Задание: [docs/contest-brief.md](docs/contest-brief.md).

## Быстрый старт

1. Откройте репозиторий в ИИ-среде (она подхватит `AGENTS.md`).
2. Опишите продуктовую задачу — агент работает по `agent/runtime-instructions.md`.
3. Нужен Python 3 (только стандартная библиотека), секреты не требуются.

## Структура

- `agent/`, `skills/`, `agents/`, `knowledge/` — продуктовый агент
- `projects/demo_mvp/` — демонстрационный кейс
- `schemas/`, `tools/`, `tests/` — ядро и проверки
- `docs/` — архитектура, решения (ADR), координация разработки

## Проверки

```
python tools/check_coordination.py
python -m unittest discover -s tests/unit
```

Подробнее: [docs/architecture.md](docs/architecture.md), [docs/decisions.md](docs/decisions.md).
