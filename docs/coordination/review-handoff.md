# Журнал передач на ревью и аудита

**Строго append-only.** Существующие записи никогда не удаляются и не редактируются. Новые записи добавляются в конец файла.

Формат записи (секция `## [HANDOFF] TASK-XXX — YYYY-MM-DD HH:MM` или `## [AUDIT] TASK-XXX — ...`):

```
task_id: TASK-XXX
record_type: HANDOFF | AUDIT
author: <чат>
timestamp: YYYY-MM-DD HH:MM
commit_hash: <короткий хэш>
agents_md_sha256: <sha256>
changed_files: ...
verified_checks: ...
limitations: ...
predecessor_ref: NONE
```

---

## [HANDOFF] TASK-000 — 2026-11-09 10:16
task_id: TASK-000
record_type: HANDOFF
author: Sonnet-Staff
timestamp: 2026-11-09 10:16
commit_hash: d6e54f7
agents_md_sha256: 57bf75979bd8d3b17fef9c137c09f9b96bbf5504b8699080955c13da9c900b73
changed_files: AGENTS.md, CLAUDE.md, .cursorrules, README.md, .gitignore, .gitattributes, .env.example, .agents/skills.json, agent/runtime-instructions.md, docs/ (contest-brief, architecture, decisions, coordination/*), tools/check_coordination.py, tests/unit/test_check_coordination.py, каркас каталогов с .gitkeep
verified_checks: python tools/check_coordination.py -> PASS; python -m unittest discover -s tests/unit -> OK
limitations: ТЗ.txt закоммичен без изменений; git user задан локально (Sonnet-Staff); docs/contest-brief.md — ТЗ с добавленными заголовками
predecessor_ref: NONE
