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
