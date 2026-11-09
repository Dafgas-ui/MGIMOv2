"""Проверка целостности системы координации (только стандартная библиотека).

Запуск: python tools/check_coordination.py
Код возврата: 0 — PASS, 1 — есть ошибки.
"""
import hashlib
import re
import sys
from pathlib import Path

COORD_FILES = ["workflow.md", "task-board.md", "project-status.md", "review-handoff.md"]
COLUMNS = ["task_id", "title", "assignee", "reviewer", "dev_status",
           "audit_status", "owner_status", "commit_ref", "notes"]
DEV = {"PLANNED", "IN_PROGRESS", "READY_FOR_REVIEW"}
AUDIT = {"PENDING", "PASS", "PASS WITH WARNINGS", "FAIL", "NOT VERIFIED"}
OWNER = {"PENDING", "ACCEPTED", "ACCEPTED WITH LIMITATIONS"}
BAD_HASH = {"", "PENDING", "TBD", "-", "NONE"}
TASK_RE = re.compile(r"^TASK-\d+$")
HEADER_RE = re.compile(r"^## \[(HANDOFF|AUDIT)\]\s+(TASK-\d+)")
FIELD_RE = re.compile(r"^\s*(?:[-*]\s*)?(\w+)\s*:\s*(.*)$")

REQUIRED_RECORD_FIELDS = (
    "task_id",
    "record_type",
    "author",
    "timestamp",
    "commit_hash",
    "agents_md_sha256",
    "changed_files",
    "verified_checks",
    "limitations",
    "predecessor_ref",
)
AUDITED_STATUSES = frozenset({"PASS", "PASS WITH WARNINGS", "FAIL"})


def _clean(v):
    return v.strip().strip("`").strip()


def _read(path):
    return path.read_text(encoding="utf-8")


def parse_task_board(text):
    """Возвращает список словарей-строк таблицы."""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [_clean(c) for c in s.strip("|").split("|")]
        if cells and cells[0] == "task_id":
            continue
        if cells and set(cells[0]) <= set("-: "):
            continue
        if len(cells) != len(COLUMNS):
            rows.append({"_bad": s})
            continue
        rows.append(dict(zip(COLUMNS, cells)))
    return rows


def parse_handoff(text):
    """Возвращает список записей (поля + record_type из заголовка), пропуская блоки кода."""
    records, cur, in_code = [], None, False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADER_RE.match(line)
        if m:
            cur = {"_type": m.group(1), "_task": m.group(2)}
            records.append(cur)
            continue
        if line.startswith("## "):
            cur = None
            continue
        if cur is not None:
            f = FIELD_RE.match(line)
            if f and f.group(1) not in cur:
                cur[f.group(1)] = _clean(f.group(2))
    return records


def check(root):
    """Возвращает список ошибок (пустой — всё хорошо)."""
    root = Path(root)
    errors = []
    coord = root / "docs" / "coordination"
    agents = root / "AGENTS.md"

    # 1. Наличие файлов
    if not agents.is_file():
        errors.append("Отсутствует AGENTS.md")
    for name in COORD_FILES:
        if not (coord / name).is_file():
            errors.append(f"Отсутствует docs/coordination/{name}")
    if errors:
        return errors

    # 2. Таблица задач
    rows = parse_task_board(_read(coord / "task-board.md"))
    if not rows:
        errors.append("task-board.md: таблица задач пуста или не найдена")
    seen = {}
    valid_rows = []
    for r in rows:
        if "_bad" in r:
            errors.append(f"task-board.md: неверное число колонок: {r['_bad']}")
            continue
        tid = r["task_id"]
        if not TASK_RE.match(tid):
            errors.append(f"task-board.md: неверный task_id '{tid}'")
        seen[tid] = seen.get(tid, 0) + 1
        for col, allowed in (("dev_status", DEV), ("audit_status", AUDIT), ("owner_status", OWNER)):
            if r[col] not in allowed:
                errors.append(f"task-board.md: {tid}: недопустимый {col} '{r[col]}'")
        valid_rows.append(r)
    for tid, n in seen.items():
        if n > 1:
            errors.append(f"task-board.md: дубликат task_id {tid} ({n} строк)")

    # 3. Сверка с handoff и audit (COORD-01)
    records = parse_handoff(_read(coord / "review-handoff.md"))

    # 3.1 Валидация полноты и корректности каждой секции handoff/audit
    for rec in records:
        tid = rec.get("_task", "UNKNOWN")
        rtype = rec.get("_type", "UNKNOWN")
        for f_name in REQUIRED_RECORD_FIELDS:
            if f_name not in rec or not rec[f_name].strip():
                errors.append(
                    f"review-handoff.md: {tid} [{rtype}]: отсутствует или пусто обязательное поле '{f_name}'"
                )
        if rec.get("task_id") != tid:
            errors.append(
                f"review-handoff.md: {tid} [{rtype}]: поле task_id '{rec.get('task_id')}' не совпадает с заголовком '{tid}'"
            )
        if rec.get("record_type") != rtype:
            errors.append(
                f"review-handoff.md: {tid} [{rtype}]: поле record_type '{rec.get('record_type')}' не совпадает с типом заголовка '{rtype}'"
            )

    # 3.2 Сверка задач из task-board.md
    for r in valid_rows:
        tid = r["task_id"]
        if r["dev_status"] == "READY_FOR_REVIEW":
            ok = any(
                rec.get("_type") == "HANDOFF" and rec.get("_task") == tid
                and rec.get("commit_hash", "").upper() not in BAD_HASH
                for rec in records
            )
            if not ok:
                errors.append(f"{tid}: READY_FOR_REVIEW, но в review-handoff.md нет блока HANDOFF с валидным commit_hash")

        if r["audit_status"] in AUDITED_STATUSES:
            ok_audit = any(
                rec.get("_type") == "AUDIT" and rec.get("_task") == tid
                and rec.get("commit_hash", "").upper() not in BAD_HASH
                for rec in records
            )
            if not ok_audit:
                errors.append(f"{tid}: audit_status равен {r['audit_status']}, но в review-handoff.md нет блока AUDIT с валидным commit_hash")

    # 4. Хэш AGENTS.md
    actual = hashlib.sha256(agents.read_bytes()).hexdigest()
    m = re.search(r"agents_md_sha256\s*:\s*`?([0-9a-fA-F]{64})`?", _read(coord / "project-status.md"))
    if not m:
        errors.append("project-status.md: не найден agents_md_sha256")
    elif m.group(1).lower() != actual:
        errors.append(f"AGENTS.md: SHA-256 не совпадает (файл {actual}, project-status {m.group(1).lower()})")
    return errors


def main():
    root = Path(__file__).resolve().parent.parent
    errors = check(root)
    if errors:
        print("COORDINATION CHECK: FAIL")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("COORDINATION CHECK: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
