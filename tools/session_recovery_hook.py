"""Хук автовосстановления сессии для Antigravity Lifecycle Hooks (SessionStart, T07).

Запуск:
  python ../tools/session_recovery_hook.py  (из рабочей директории .agents/)
  python tools/session_recovery_hook.py    (из корня репозитория)
  python tools/session_recovery_hook.py --test-case <path>

Контракт:
  - Возвращает код 0 всегда (никогда не падает с ошибкой, чтобы не блокировать сессию).
  - Если есть активные кейсы с state.json, выводит в stdout:
    {
      "injectSteps": [
        {
          "systemMessage": {
            "systemMessage": "<краткая сводка состояния активных кейсов>"
          }
        }
      ]
    }
  - Если активных кейсов нет (или при непредвиденной ошибке) — выводит:
    {}
"""
import argparse
import json
import sys
from pathlib import Path

# Обеспечиваем корректную кодировку UTF-8 на стандартном выводе
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def format_recovery_summary(summary, case_dir, root_dir):
    """Формирует компактный читаемый текст сводки для возобновления работы."""
    try:
        rel_case = case_dir.relative_to(root_dir).as_posix()
    except Exception:
        rel_case = str(case_dir)

    lines = [
        f"=== RECOVERY SUMMARY: {summary.get('case_id') or rel_case} ===",
        f"Case directory: {rel_case}",
        f"Current stage: {summary.get('current_stage') or 'UNKNOWN'} "
        f"(completed: {', '.join(summary.get('completed_stages') or []) or 'none'})",
        f"Artifacts integrity (T07): {'OK' if summary.get('artifacts_integrity_ok') else 'MODIFIED/MISSING'} "
        f"({len(summary.get('artifacts_integrity') or [])} tracked)",
    ]

    awaiting = summary.get("awaiting_human_approval") or {}
    if awaiting.get("is_awaiting"):
        lines.append(f"Awaiting human approval: YES — {awaiting.get('reason')}")
    else:
        lines.append("Awaiting human approval: NO")

    rec = summary.get("recovery")
    if rec:
        lines.append(
            f"In-progress operation (T09): op={rec.get('operation_id')} "
            f"({rec.get('status')}) -> {rec.get('safe_action')}"
        )
    else:
        lines.append("In-progress operation (T09): NONE")

    stale = summary.get("stale_nodes") or []
    if stale:
        lines.append(f"Needs reassessment / stale nodes (T08): {', '.join(stale)}")
    else:
        lines.append("Needs reassessment / stale nodes (T08): NONE")

    c = summary.get("evidence_counts") or {}
    if c:
        lines.append(
            f"Evidence graph: sources={c.get('sources', 0)}, findings={c.get('findings', 0)}, "
            f"calculations={c.get('calculations', 0)}, hypotheses={c.get('hypotheses', 0)}, "
            f"contradictions={c.get('contradictions', 0)}, gaps={c.get('knowledge_gaps', 0)}"
        )

    t = summary.get("cost_totals") or {}
    lines.append(
        f"Usage & cost totals (T11): duration={t.get('total_duration_sec', 0)}s, "
        f"tokens={t.get('total_tokens', 0)}, cost=${t.get('total_estimated_cost_usd', 0):.4f}"
    )
    lines.append(f"Resume command: python tools/strategist_cli.py resume --case {rel_case}")
    return "\n".join(lines)


def generate_recovery_payload(root_dir=None, test_case=None):
    """Сканирует кейсы и возвращает структуру хука или пустой словарь."""
    root = Path(root_dir).resolve() if root_dir else Path(__file__).resolve().parent.parent

    try:
        import strategist_cli as sc
    except Exception:
        return {}

    case_dirs = []
    if test_case:
        cand = Path(test_case)
        if not cand.is_absolute():
            cand = (root / cand).resolve()
        if (cand / "state.json").is_file():
            case_dirs = [cand]
    else:
        projects_dir = root / "projects"
        if projects_dir.is_dir():
            for state_file in sorted(projects_dir.glob("*/state.json")):
                if state_file.is_file():
                    case_dirs.append(state_file.parent)

    if not case_dirs:
        return {}

    summaries = []
    for cdir in case_dirs:
        try:
            status = sc.get_case_status(cdir)
            summaries.append(format_recovery_summary(status, cdir, root))
        except Exception:
            continue

    if not summaries:
        return {}

    combined_text = "\n\n".join(summaries)
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": combined_text
                }
            }
        ]
    }


def main():
    try:
        parser = argparse.ArgumentParser(description="Hook for session state recovery (T07).")
        parser.add_argument("--test-case", dest="test_case", help="Путь к конкретному кейсу для тестирования")
        args, _ = parser.parse_known_args()

        payload = generate_recovery_payload(test_case=args.test_case)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0
    except Exception:
        sys.stdout.write("{}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
